# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The support endpoint, exercised over HTTP.

The rest of the support tests call `create_support_request` directly, which
skips everything the view does: reading the posted address, checking it, and
deciding what the customer is told. That gap let a malformed address through
to production, where one trailing comma took out the confirmation email, our
own internal notification (the address rides along in Reply-To) and the
tracker's email link, from a form that had already said "Message sent".

Anything reachable only through a request needs at least one test that makes
the request.
"""
from dataclasses import dataclass
from unittest import mock

import pytest
from django.test import Client

from payglue_backend.tenants.models import (
    SupportRequest,
    Tenant,
    TenantMembership,
    UserProfile,
)

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class _StubClaims:
    firebase_uid: str
    email: str


class _StubVerifier:
    def __init__(self, claims: _StubClaims) -> None:
        self._claims = claims

    def verify(self, token: str) -> _StubClaims:
        del token
        return self._claims


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(slug="acme", schema_name="acme")


@pytest.fixture
def headers(monkeypatch, tenant: Tenant) -> dict[str, str]:
    profile = UserProfile.objects.create(firebase_uid="uid-1", email="signed-in@example.com")
    TenantMembership.objects.create(
        tenant=tenant, user_profile=profile, role=TenantMembership.Role.OWNER
    )
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(
            _StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)
        ),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


def _post(headers: dict[str, str], **payload):
    body = {
        "name": "Sam",
        "email": "sam@example.com",
        "subject": "Paywall stays blank",
        "message": "Nothing happens after the purchase.",
        "topic": "bug",
    }
    body.update(payload)
    with mock.patch(
        "payglue_backend.tenants.support.tracker.create_support_issue",
        return_value=("iss_1", "PGSUP-1"),
    ), mock.patch("payglue_backend.tenants.support.tracker.link_requester_email"):
        return Client().post(
            "/t/acme/api/v1/support/requests",
            data=body,
            content_type="application/json",
            **headers,
        )


def test_a_valid_request_is_accepted(headers) -> None:
    resp = _post(headers)

    assert resp.status_code == 201
    assert SupportRequest.objects.count() == 1


def test_the_address_from_the_form_is_the_one_we_answer(headers) -> None:
    _post(headers, email="elsewhere@example.com")

    request = SupportRequest.objects.get()
    assert request.email == "elsewhere@example.com"
    assert request.account_email == "signed-in@example.com"


def test_a_trailing_comma_is_refused(headers) -> None:
    """The one that got through. Everything downstream trusts this address."""
    resp = _post(headers, email="nuenni@gmail.com,")

    assert resp.status_code == 400
    assert not SupportRequest.objects.exists()


@pytest.mark.parametrize(
    "value",
    [
        "nuenni@gmail.com;",
        "one@example.com, two@example.com",
        "Nuenni <nuenni@gmail.com>",
        "nuenni@gmail",
        "@gmail.com",
        "not an address",
    ],
)
def test_the_other_ways_a_paste_goes_wrong_are_refused(headers, value: str) -> None:
    assert _post(headers, email=value).status_code == 400
    assert not SupportRequest.objects.exists()


def test_an_empty_address_falls_back_to_the_account(headers) -> None:
    """Leaving it blank is not an error, it just means the obvious thing."""
    resp = _post(headers, email="")

    assert resp.status_code == 201
    assert SupportRequest.objects.get().email == "signed-in@example.com"


def test_nothing_is_stored_when_the_message_is_missing(headers) -> None:
    resp = _post(headers, message="   ")

    assert resp.status_code == 400
    assert not SupportRequest.objects.exists()

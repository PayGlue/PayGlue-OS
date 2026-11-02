# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PayPal plans come with their subscribe link.

PayPal has no hosted checkout per plan, so the product list used to return an
empty checkout_url and the docs asked for the link to be pasted by hand. A
paywall saved with a PayPal plan and no link then showed its overlay without
any button. Every plan has a fixed subscribe link though, the same one the
PayPal dashboard offers as "Share link", for sandbox and for live.
"""

import io
import json
from dataclasses import dataclass

import pytest
from django.test import Client

from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class _Claims:
    firebase_uid: str
    email: str


class _Verifier:
    def __init__(self, claims: _Claims) -> None:
        self._claims = claims

    def verify(self, token: str) -> _Claims:
        return self._claims


class _Credentials:
    def __init__(self, sandbox: bool) -> None:
        self._sandbox = sandbox

    def get_credentials(self, tenant_ctx, provider_key):
        return {"client_id": "cid", "client_secret": "csecret", "sandbox": "true" if self._sandbox else ""}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def _fake_urlopen(req, timeout=None):
    url = req.full_url
    if url.endswith("/v1/oauth2/token"):
        return _Response(json.dumps({"access_token": "tok"}).encode())
    if "/v1/billing/plans" in url:
        return _Response(json.dumps({"plans": [{"id": "P-123ABC", "name": "Supporter"}]}).encode())
    raise AssertionError(f"unexpected request {url}")


@pytest.mark.parametrize(
    ("sandbox", "host"),
    [(False, "https://www.paypal.com"), (True, "https://www.sandbox.paypal.com")],
)
def test_paypal_plans_carry_their_subscribe_link(monkeypatch: pytest.MonkeyPatch, sandbox: bool, host: str) -> None:
    tenant = Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")
    owner = UserProfile.objects.create(firebase_uid="uid-owner", email="owner@example.com")
    TenantMembership.objects.create(tenant=tenant, user_profile=owner, role=TenantMembership.Role.OWNER)
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _Verifier(_Claims(firebase_uid=owner.firebase_uid, email=owner.email)),
    )
    monkeypatch.setattr("payglue_backend.webhooks.wiring.get_credential_provider", lambda: _Credentials(sandbox))
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    response = Client().get("/t/tenant-a/api/v1/billing/paypal-products", HTTP_AUTHORIZATION="Bearer stub.header.signature")

    assert response.status_code == 200
    product = response.json()["products"][0]
    assert product["id"] == "P-123ABC"
    assert product["checkout_url"] == f"{host}/webapps/billing/plans/subscribe?plan_id=P-123ABC"

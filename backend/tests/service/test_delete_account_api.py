# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The self-service delete endpoint, exercised over HTTP.

This file exists because of a bug it would have caught in seconds. PG-203
shipped with six of the view's imports missing: `manage.py check` passed and
gunicorn booted, because Python does not resolve names inside a method body
until the method runs. The unit tests covered `require_step_up` in isolation
and never once called the endpoint, so the first thing to find out was a user
pressing "Delete my account" and getting a 500.

Anything reachable only through a request needs at least one test that makes
the request.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from unittest import mock

import pytest
from django.test import Client
from django.utils import timezone

from payglue_backend.tenants.models import (
    StepUpChallenge,
    StepUpGrant,
    Tenant,
    TenantMembership,
    UserProfile,
)

pytestmark = pytest.mark.django_db

_URL = "/api/v1/auth/account"


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


def _profile(uid: str = "uid-del", email: str = "del@example.com") -> UserProfile:
    return UserProfile.objects.create(firebase_uid=uid, email=email)


def _auth_as(monkeypatch: pytest.MonkeyPatch, profile: UserProfile) -> dict[str, str]:
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(_StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


def _grant(profile: UserProfile) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    StepUpGrant.objects.create(
        user_profile=profile,
        purpose=StepUpChallenge.Purpose.DELETE_ACCOUNT,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    return {"HTTP_X_STEP_UP_TOKEN": token}


def test_confirmed_delete_removes_the_profile(monkeypatch) -> None:
    profile = _profile()
    headers = {**_auth_as(monkeypatch, profile), **_grant(profile)}

    with mock.patch("payglue_backend.authn.views.delete_supabase_user") as supa:
        resp = Client().delete(_URL, **headers)

    assert resp.status_code == 204
    assert not UserProfile.objects.filter(id=profile.id).exists()
    supa.assert_called_once_with("uid-del")


def test_delete_takes_the_solely_owned_tenant_with_it(monkeypatch) -> None:
    profile = _profile()
    tenant = Tenant.objects.create(slug="solo-pub", schema_name="solo_pub")
    TenantMembership.objects.create(
        tenant=tenant, user_profile=profile, role=TenantMembership.Role.OWNER
    )
    headers = {**_auth_as(monkeypatch, profile), **_grant(profile)}

    with mock.patch("payglue_backend.authn.views.delete_supabase_user"):
        resp = Client().delete(_URL, **headers)

    assert resp.status_code == 204
    assert not Tenant.objects.filter(slug="solo-pub").exists()


def test_a_shared_tenant_survives(monkeypatch) -> None:
    """Leaving must not delete a publication somebody else also owns."""
    profile = _profile()
    other = _profile("uid-other", "other@example.com")
    tenant = Tenant.objects.create(slug="shared-pub", schema_name="shared_pub")
    TenantMembership.objects.create(
        tenant=tenant, user_profile=profile, role=TenantMembership.Role.OWNER
    )
    TenantMembership.objects.create(
        tenant=tenant, user_profile=other, role=TenantMembership.Role.OWNER
    )
    headers = {**_auth_as(monkeypatch, profile), **_grant(profile)}

    with mock.patch("payglue_backend.authn.views.delete_supabase_user"):
        resp = Client().delete(_URL, **headers)

    assert resp.status_code == 204
    assert Tenant.objects.filter(slug="shared-pub").exists()
    assert UserProfile.objects.filter(id=other.id).exists()


def test_without_a_grant_nothing_is_deleted(monkeypatch) -> None:
    """The API called directly, skipping the confirmation dialog entirely."""
    profile = _profile()

    resp = Client().delete(_URL, **_auth_as(monkeypatch, profile))

    assert resp.status_code == 403
    assert UserProfile.objects.filter(id=profile.id).exists()


def test_somebody_elses_grant_does_not_work(monkeypatch) -> None:
    profile = _profile()
    other = _profile("uid-other", "other@example.com")
    headers = {**_auth_as(monkeypatch, profile), **_grant(other)}

    resp = Client().delete(_URL, **headers)

    assert resp.status_code == 403
    assert UserProfile.objects.filter(id=profile.id).exists()


def test_the_grant_cannot_be_replayed(monkeypatch) -> None:
    """A spent grant must not delete a second account after a re-signup."""
    profile = _profile()
    step_up = _grant(profile)

    with mock.patch("payglue_backend.authn.views.delete_supabase_user"):
        first = Client().delete(_URL, **{**_auth_as(monkeypatch, profile), **step_up})
    assert first.status_code == 204

    again = _profile("uid-del-2", "del2@example.com")
    resp = Client().delete(_URL, **{**_auth_as(monkeypatch, again), **step_up})

    assert resp.status_code == 403
    assert UserProfile.objects.filter(id=again.id).exists()


def test_local_data_still_goes_when_supabase_fails(monkeypatch) -> None:
    """Supabase is last and outside the transaction on purpose: the data we are
    obliged to remove must not survive because an external call had a bad day."""
    from payglue_backend.tenants.supabase_admin import SupabaseAdminError

    profile = _profile()
    headers = {**_auth_as(monkeypatch, profile), **_grant(profile)}

    with mock.patch(
        "payglue_backend.authn.views.delete_supabase_user",
        side_effect=SupabaseAdminError("boom"),
    ):
        resp = Client().delete(_URL, **headers)

    assert resp.status_code == 204
    assert not UserProfile.objects.filter(id=profile.id).exists()


def test_the_user_gets_a_deletion_receipt(monkeypatch) -> None:
    """The one action a user cannot undo was the one producing no email."""
    from django.core import mail

    profile = _profile()
    headers = {**_auth_as(monkeypatch, profile), **_grant(profile)}
    mail.outbox.clear()

    with mock.patch("payglue_backend.authn.views.delete_supabase_user"):
        resp = Client().delete(_URL, **headers)

    assert resp.status_code == 204
    # Exactly one mail to the user. A deletion also notifies us now, so this
    # asserts on the customer's mail rather than on the whole outbox.
    user_mails = [m for m in mail.outbox if m.to == ["del@example.com"]]
    assert len(user_mails) == 1
    assert "deleted" in user_mails[0].subject.lower()


def test_the_receipt_does_not_promise_a_deadline(monkeypatch) -> None:
    """Deletion is synchronous, so the copy must not say "within 24 hours" or
    "within 30 days". Either would understate what happened and contradict the
    DPA, which carries 30 days as an outer bound rather than a queue."""
    from django.core import mail

    profile = _profile()
    headers = {**_auth_as(monkeypatch, profile), **_grant(profile)}
    mail.outbox.clear()

    with mock.patch("payglue_backend.authn.views.delete_supabase_user"):
        Client().delete(_URL, **headers)

    # Explicitly the user's mail, not just whichever went out first: the admin
    # notification shares the outbox and ordering is not a contract.
    body = next(m for m in mail.outbox if m.to == ["del@example.com"]).body.lower()
    assert "24 hours" not in body
    assert "within 30 days" not in body
    assert "has been deleted" in body
    # The statutory-retention caveat is not optional: the privacy policy keeps
    # payment records, so a mail claiming everything is gone would be false.
    assert "invoices" in body
    # And it must not claim custody of records we do not hold. They live with
    # the payment provider; we could not delete them if we wanted to.
    assert "not ours to delete" in body
    # Backups outlive the deletion by a week from 2026-08-01. Saying so early
    # over-discloses, which is the harmless direction.
    assert "7-day rolling window" in body


def test_a_failed_send_does_not_undo_the_deletion(monkeypatch) -> None:
    """The account is already gone by then; raising would turn a successful
    deletion into a 500 for something that did succeed."""
    profile = _profile()
    headers = {**_auth_as(monkeypatch, profile), **_grant(profile)}

    with mock.patch("payglue_backend.authn.views.delete_supabase_user"), mock.patch(
        "payglue_backend.authn.lifecycle_emails._send_branded",
        side_effect=RuntimeError("smtp down"),
    ):
        resp = Client().delete(_URL, **headers)

    assert resp.status_code == 204
    assert not UserProfile.objects.filter(id=profile.id).exists()


def test_deletion_notifies_the_admin_with_the_blast_radius(
    monkeypatch, mailoutbox, settings
) -> None:
    """A customer leaving should not be something we notice by chance."""
    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    profile = _profile()
    other = _profile("uid-other", "other@example.com")
    solo = Tenant.objects.create(slug="solo-pub", schema_name="solo_pub")
    shared = Tenant.objects.create(slug="shared-pub", schema_name="shared_pub")
    for tenant in (solo, shared):
        TenantMembership.objects.create(
            tenant=tenant, user_profile=profile, role=TenantMembership.Role.OWNER
        )
    TenantMembership.objects.create(
        tenant=shared, user_profile=other, role=TenantMembership.Role.OWNER
    )
    headers = {**_auth_as(monkeypatch, profile), **_grant(profile)}

    with mock.patch("payglue_backend.authn.views.delete_supabase_user"):
        assert Client().delete(_URL, **headers).status_code == 204

    admin_mails = [m for m in mailoutbox if "ops@example.com" in m.to]
    assert len(admin_mails) == 1
    assert "del@example.com" in admin_mails[0].subject
    body = admin_mails[0].body
    # One publication died with them, one they merely left.
    assert "Workspaces deleted with them: 1" in body
    assert "Workspaces they only left (other owners remain): 1" in body


def test_a_failing_admin_notification_does_not_break_the_deletion(
    monkeypatch, settings
) -> None:
    """The account is already gone when this fires; a broken mailer must not
    turn a successful deletion into a 500."""
    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    profile = _profile()
    headers = {**_auth_as(monkeypatch, profile), **_grant(profile)}

    with (
        mock.patch("payglue_backend.authn.views.delete_supabase_user"),
        mock.patch(
            "payglue_backend.authn.lifecycle_emails._send_branded",
            side_effect=RuntimeError("smtp is down"),
        ),
    ):
        resp = Client().delete(_URL, **headers)

    assert resp.status_code == 204
    assert not UserProfile.objects.filter(id=profile.id).exists()

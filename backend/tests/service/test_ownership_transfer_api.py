# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-182: ownership transfer is a confirmed flow. Owner/admin requests it, the
current owner is emailed and alone confirms/rejects; on confirm the new member
becomes owner and the old owner becomes billing_admin (billing stays)."""
from dataclasses import dataclass

import pytest
from django.core import mail
from django.test import Client

from payglue_backend.tenants.models import (
    OwnershipTransferRequest,
    Tenant,
    TenantMembership,
    UserProfile,
)

pytestmark = pytest.mark.django_db

_TRANSFER_URL = "/t/tenant-a/api/v1/team/ownership-transfer"
_ACTION_URL = "/t/tenant-a/api/v1/team/ownership-transfer/action"


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


@pytest.fixture(autouse=True)
def _seed_tenant() -> None:
    Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")


def _member(uid: str, email: str, role: str) -> TenantMembership:
    tenant = Tenant.objects.get(slug="tenant-a")
    profile = UserProfile.objects.create(firebase_uid=uid, email=email)
    return TenantMembership.objects.create(tenant=tenant, user_profile=profile, role=role)


def _auth_as(monkeypatch: pytest.MonkeyPatch, membership: TenantMembership) -> dict[str, str]:
    profile = membership.user_profile
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(_StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


def _step_up(membership: TenantMembership) -> dict[str, str]:
    """PG-203: confirming now needs a spent step-up grant. Minted directly here
    rather than driving the email round trip, which has its own tests in
    tests/unit/test_step_up.py -- this file is about the transfer rules."""
    import hashlib
    import secrets
    from datetime import timedelta

    from django.utils import timezone

    from payglue_backend.tenants.models import StepUpChallenge, StepUpGrant

    token = secrets.token_urlsafe(32)
    StepUpGrant.objects.create(
        user_profile=membership.user_profile,
        purpose=StepUpChallenge.Purpose.OWNER_TRANSFER,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    return {"HTTP_X_STEP_UP_TOKEN": token}


def _pending(tenant_slug: str = "tenant-a") -> OwnershipTransferRequest | None:
    return OwnershipTransferRequest.objects.filter(
        tenant__slug=tenant_slug, status=OwnershipTransferRequest.Status.PENDING
    ).first()


def test_owner_requests_transfer_creates_pending_and_emails_both_parties(monkeypatch) -> None:
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)
    headers = _auth_as(monkeypatch, owner)

    resp = Client().post(
        _TRANSFER_URL, {"new_owner_membership_id": target.id}, content_type="application/json", **headers
    )

    assert resp.status_code == 201
    tr = _pending()
    assert tr is not None
    assert tr.current_owner_id == owner.user_profile_id
    assert tr.new_owner_id == target.user_profile_id
    # The current owner gets the confirm/reject decision; the proposed owner
    # gets their own heads-up. Two distinct mails, never one mail to both --
    # only the current owner may act on it.
    assert {tuple(m.to) for m in mail.outbox} == {("owner@example.com",), ("member@example.com",)}
    proposed = next(m for m in mail.outbox if m.to == ["member@example.com"])
    assert "proposed" in proposed.subject.lower()


def test_admin_may_request_but_billing_admin_may_not(monkeypatch) -> None:
    _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)

    billing = _member("billing", "billing@example.com", TenantMembership.Role.BILLING_ADMIN)
    resp = Client().post(_TRANSFER_URL, {"new_owner_membership_id": target.id}, content_type="application/json", **_auth_as(monkeypatch, billing))
    assert resp.status_code == 403
    assert _pending() is None

    admin = _member("admin", "admin@example.com", TenantMembership.Role.ADMIN)
    resp = Client().post(_TRANSFER_URL, {"new_owner_membership_id": target.id}, content_type="application/json", **_auth_as(monkeypatch, admin))
    assert resp.status_code == 201
    assert _pending() is not None


def test_only_one_pending_transfer_at_a_time(monkeypatch) -> None:
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)
    headers = _auth_as(monkeypatch, owner)
    Client().post(_TRANSFER_URL, {"new_owner_membership_id": target.id}, content_type="application/json", **headers)

    resp = Client().post(_TRANSFER_URL, {"new_owner_membership_id": target.id}, content_type="application/json", **headers)
    assert resp.status_code == 409


def test_confirm_by_current_owner_swaps_roles(monkeypatch) -> None:
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)
    OwnershipTransferRequest.objects.create(
        tenant=owner.tenant, current_owner=owner.user_profile,
        new_owner=target.user_profile, requested_by=owner.user_profile,
    )

    resp = Client().post(
        _ACTION_URL,
        {"action": "confirm"},
        content_type="application/json",
        **_auth_as(monkeypatch, owner),
        **_step_up(owner),
    )

    assert resp.status_code == 200
    target.refresh_from_db()
    owner.refresh_from_db()
    assert target.role == TenantMembership.Role.OWNER
    assert owner.role == TenantMembership.Role.BILLING_ADMIN
    assert _pending() is None


def test_non_owner_cannot_confirm(monkeypatch) -> None:
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)
    OwnershipTransferRequest.objects.create(
        tenant=owner.tenant, current_owner=owner.user_profile,
        new_owner=target.user_profile, requested_by=owner.user_profile,
    )

    resp = Client().post(_ACTION_URL, {"action": "confirm"}, content_type="application/json", **_auth_as(monkeypatch, target))

    assert resp.status_code == 403
    target.refresh_from_db()
    assert target.role == TenantMembership.Role.ADMIN  # unchanged


def test_reject_by_owner_leaves_roles_unchanged(monkeypatch) -> None:
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)
    OwnershipTransferRequest.objects.create(
        tenant=owner.tenant, current_owner=owner.user_profile,
        new_owner=target.user_profile, requested_by=owner.user_profile,
    )

    resp = Client().post(_ACTION_URL, {"action": "reject"}, content_type="application/json", **_auth_as(monkeypatch, owner))

    assert resp.status_code == 200
    owner.refresh_from_db()
    target.refresh_from_db()
    assert owner.role == TenantMembership.Role.OWNER
    assert target.role == TenantMembership.Role.ADMIN
    assert _pending() is None


def test_confirm_notifies_every_party(monkeypatch) -> None:
    """An ownership change is security-relevant, so everyone involved gets a
    receipt -- including the requester, who may be an admin who isn't either
    of the two owners."""
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)
    requester = _member("admin", "admin@example.com", TenantMembership.Role.ADMIN)
    OwnershipTransferRequest.objects.create(
        tenant=owner.tenant, current_owner=owner.user_profile,
        new_owner=target.user_profile, requested_by=requester.user_profile,
    )
    mail.outbox.clear()

    resp = Client().post(
        _ACTION_URL,
        {"action": "confirm"},
        content_type="application/json",
        **_auth_as(monkeypatch, owner),
        **_step_up(owner),
    )

    assert resp.status_code == 200
    assert {tuple(m.to) for m in mail.outbox} == {
        ("owner@example.com",), ("member@example.com",), ("admin@example.com",)
    }
    assert "member@example.com" in mail.outbox[0].subject


def test_reject_notifies_every_party(monkeypatch) -> None:
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)
    OwnershipTransferRequest.objects.create(
        tenant=owner.tenant, current_owner=owner.user_profile,
        new_owner=target.user_profile, requested_by=owner.user_profile,
    )
    mail.outbox.clear()

    resp = Client().post(_ACTION_URL, {"action": "reject"}, content_type="application/json", **_auth_as(monkeypatch, owner))

    assert resp.status_code == 200
    # Owner is both current_owner and requester here: deduped to one mail each.
    assert {tuple(m.to) for m in mail.outbox} == {
        ("owner@example.com",), ("member@example.com",)
    }
    assert "called off" in mail.outbox[0].subject


def test_cancel_notifies_like_a_rejection(monkeypatch) -> None:
    """From the outside cancel and reject are the same outcome (nothing
    changed), so they share one template."""
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)
    OwnershipTransferRequest.objects.create(
        tenant=owner.tenant, current_owner=owner.user_profile,
        new_owner=target.user_profile, requested_by=owner.user_profile,
    )
    mail.outbox.clear()

    resp = Client().post(_ACTION_URL, {"action": "cancel"}, content_type="application/json", **_auth_as(monkeypatch, owner))

    assert resp.status_code == 200
    assert "called off" in mail.outbox[0].subject


def test_cannot_promote_to_owner_via_patch(monkeypatch) -> None:
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)

    resp = Client().patch(
        f"/t/tenant-a/api/v1/team/{target.id}",
        {"role": TenantMembership.Role.OWNER},
        content_type="application/json",
        **_auth_as(monkeypatch, owner),
    )

    assert resp.status_code == 400
    target.refresh_from_db()
    assert target.role == TenantMembership.Role.ADMIN


def test_confirm_without_step_up_is_refused(monkeypatch) -> None:
    """PG-203: the whole point. A confirm that skips the overlay, by calling the
    API directly, must not go through."""
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)
    OwnershipTransferRequest.objects.create(
        tenant=owner.tenant, current_owner=owner.user_profile,
        new_owner=target.user_profile, requested_by=owner.user_profile,
    )

    resp = Client().post(
        _ACTION_URL, {"action": "confirm"}, content_type="application/json",
        **_auth_as(monkeypatch, owner),
    )

    assert resp.status_code == 403
    owner.refresh_from_db()
    target.refresh_from_db()
    assert owner.role == TenantMembership.Role.OWNER
    assert target.role == TenantMembership.Role.ADMIN
    assert _pending() is not None


def test_reject_needs_no_step_up(monkeypatch) -> None:
    """Rejecting changes nothing, so it stays one click."""
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.ADMIN)
    OwnershipTransferRequest.objects.create(
        tenant=owner.tenant, current_owner=owner.user_profile,
        new_owner=target.user_profile, requested_by=owner.user_profile,
    )

    resp = Client().post(
        _ACTION_URL, {"action": "reject"}, content_type="application/json",
        **_auth_as(monkeypatch, owner),
    )

    assert resp.status_code == 200

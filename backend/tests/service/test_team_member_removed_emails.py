# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Removing a team member used to be silent: the person simply lost access,
with nothing saying why or by whom, and nobody answerable for the publication
was told either. Access changes that leave no trace are how quiet takeovers
work, which is why the ownership transfer already mails every party."""
from dataclasses import dataclass

import pytest
from django.core import mail
from django.test import Client

from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile

pytestmark = pytest.mark.django_db

_TEAM_URL = "/t/tenant-a/api/v1/team"


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


def _remove(monkeypatch, actor: TenantMembership, target: TenantMembership):
    return Client().delete(f"{_TEAM_URL}/{target.id}", **_auth_as(monkeypatch, actor))


def test_removed_member_and_owner_are_both_told(monkeypatch) -> None:
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.SUPPORT_READONLY)
    mail.outbox.clear()

    resp = _remove(monkeypatch, owner, target)

    assert resp.status_code == 204
    assert {tuple(m.to) for m in mail.outbox} == {
        ("member@example.com",),
        ("owner@example.com",),
    }


def test_the_two_audiences_get_different_copy(monkeypatch) -> None:
    """"You have been removed" is wrong for an owner, and "X was removed" is a
    strange way to tell somebody it was them."""
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.SUPPORT_READONLY)
    mail.outbox.clear()

    _remove(monkeypatch, owner, target)

    to_removed = next(m for m in mail.outbox if m.to == ["member@example.com"])
    to_owner = next(m for m in mail.outbox if m.to == ["owner@example.com"])
    assert to_removed.subject != to_owner.subject
    assert "You were removed" in to_removed.subject
    assert "member@example.com" in to_owner.subject


def test_removed_member_does_not_get_the_owners_receipt(monkeypatch) -> None:
    """The receipt names who else was informed; the removed person is not
    entitled to that list."""
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.SUPPORT_READONLY)
    mail.outbox.clear()

    _remove(monkeypatch, owner, target)

    to_member = [m for m in mail.outbox if m.to == ["member@example.com"]]
    assert len(to_member) == 1


def test_an_admin_removal_still_reaches_the_owner(monkeypatch) -> None:
    """The case the feature exists for: an admin quietly dropping somebody must
    not be invisible to the owner."""
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    admin = _member("admin", "admin@example.com", TenantMembership.Role.ADMIN)
    target = _member("member", "member@example.com", TenantMembership.Role.SUPPORT_READONLY)
    mail.outbox.clear()

    _remove(monkeypatch, admin, target)

    recipients = {tuple(m.to) for m in mail.outbox}
    assert ("owner@example.com",) in recipients
    assert ("admin@example.com",) in recipients
    assert ("member@example.com",) in recipients


def test_every_owner_hears_about_it(monkeypatch) -> None:
    """One owner being told is not enough when a publication has several."""
    owner_a = _member("owner-a", "a@example.com", TenantMembership.Role.OWNER)
    _member("owner-b", "b@example.com", TenantMembership.Role.OWNER)
    target = _member("member", "member@example.com", TenantMembership.Role.SUPPORT_READONLY)
    mail.outbox.clear()

    _remove(monkeypatch, owner_a, target)

    recipients = {tuple(m.to) for m in mail.outbox}
    assert ("a@example.com",) in recipients
    assert ("b@example.com",) in recipients


def test_a_removed_owner_is_not_mailed_their_own_receipt(monkeypatch) -> None:
    """A removed owner would otherwise appear in the owner list they are being
    removed from, and receive both mails."""
    owner_a = _member("owner-a", "a@example.com", TenantMembership.Role.OWNER)
    owner_b = _member("owner-b", "b@example.com", TenantMembership.Role.OWNER)
    mail.outbox.clear()

    resp = _remove(monkeypatch, owner_a, owner_b)

    assert resp.status_code == 204
    to_removed = [m for m in mail.outbox if m.to == ["b@example.com"]]
    assert len(to_removed) == 1
    assert "You were removed" in to_removed[0].subject


def test_a_failed_removal_sends_nothing(monkeypatch) -> None:
    """Removing the last owner is refused, so nobody may be told it happened."""
    owner = _member("owner", "owner@example.com", TenantMembership.Role.OWNER)
    mail.outbox.clear()

    resp = _remove(monkeypatch, owner, owner)

    assert resp.status_code == 400
    assert mail.outbox == []

from dataclasses import dataclass

import pytest
from django.test import Client

from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile


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


@pytest.fixture(autouse=True)
def _seed_tenant() -> None:
    Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")


def _auth_headers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    role: str,
    uid_suffix: str,
) -> tuple[dict[str, str], TenantMembership]:
    tenant = Tenant.objects.get(slug="tenant-a")
    profile = UserProfile.objects.create(
        firebase_uid=f"uid-{uid_suffix}",
        email=f"{uid_suffix}@example.com",
    )
    membership = TenantMembership.objects.create(
        tenant=tenant,
        user_profile=profile,
        role=role,
    )
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(
            _StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)
        ),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}, membership


@pytest.mark.parametrize(
    ("role", "can_write"),
    [
        (TenantMembership.Role.OWNER, True),
        (TenantMembership.Role.ADMIN, True),
        (TenantMembership.Role.BILLING_ADMIN, False),
        (TenantMembership.Role.SUPPORT_READONLY, False),
    ],
)
def test_team_api_permission_matrix(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    can_write: bool,
) -> None:
    client = Client()
    headers, actor_membership = _auth_headers(
        monkeypatch,
        role=role,
        uid_suffix=f"team-{role}",
    )
    invitee = UserProfile.objects.create(
        firebase_uid=f"invitee-{role}",
        email=f"invitee-{role}@example.com",
    )

    list_response = client.get("/t/tenant-a/api/v1/team", **headers)
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    post_response = client.post(
        "/t/tenant-a/api/v1/team",
        data={"email": invitee.email, "role": TenantMembership.Role.ADMIN},
        content_type="application/json",
        **headers,
    )
    assert post_response.status_code == (201 if can_write else 403)

    if can_write:
        membership_id = post_response.json()["id"]
    else:
        membership_id = actor_membership.id

    patch_response = client.patch(
        f"/t/tenant-a/api/v1/team/{membership_id}",
        data={"role": TenantMembership.Role.BILLING_ADMIN},
        content_type="application/json",
        **headers,
    )
    assert patch_response.status_code == (200 if can_write else 403)

    if can_write:
        delete_target_id = membership_id
    else:
        delete_target_id = actor_membership.id
    delete_response = client.delete(
        f"/t/tenant-a/api/v1/team/{delete_target_id}",
        **headers,
    )
    assert delete_response.status_code == (204 if can_write else 403)


def test_team_api_prevents_last_owner_removal_and_demotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers, owner_membership = _auth_headers(
        monkeypatch,
        role=TenantMembership.Role.OWNER,
        uid_suffix="solo-owner",
    )

    demote_response = client.patch(
        f"/t/tenant-a/api/v1/team/{owner_membership.id}",
        data={"role": TenantMembership.Role.ADMIN},
        content_type="application/json",
        **headers,
    )
    assert demote_response.status_code == 400

    remove_response = client.delete(
        f"/t/tenant-a/api/v1/team/{owner_membership.id}",
        **headers,
    )
    assert remove_response.status_code == 400


def test_team_api_prevents_admin_owner_escalation_and_owner_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    owner_profile = UserProfile.objects.create(
        firebase_uid="uid-owner",
        email="owner@example.com",
    )
    tenant = Tenant.objects.get(slug="tenant-a")
    owner_membership = TenantMembership.objects.create(
        tenant=tenant,
        user_profile=owner_profile,
        role=TenantMembership.Role.OWNER,
    )
    headers, _ = _auth_headers(
        monkeypatch,
        role=TenantMembership.Role.ADMIN,
        uid_suffix="admin-guard",
    )
    invitee = UserProfile.objects.create(
        firebase_uid="uid-invitee-owner",
        email="invitee-owner@example.com",
    )

    post_owner_response = client.post(
        "/t/tenant-a/api/v1/team",
        data={"email": invitee.email, "role": TenantMembership.Role.OWNER},
        content_type="application/json",
        **headers,
    )
    assert post_owner_response.status_code == 403

    patch_owner_response = client.patch(
        f"/t/tenant-a/api/v1/team/{owner_membership.id}",
        data={"role": TenantMembership.Role.ADMIN},
        content_type="application/json",
        **headers,
    )
    assert patch_owner_response.status_code == 403

    delete_owner_response = client.delete(
        f"/t/tenant-a/api/v1/team/{owner_membership.id}",
        **headers,
    )
    assert delete_owner_response.status_code == 403


def test_team_api_returns_400_on_email_uid_conflict_in_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers, _ = _auth_headers(
        monkeypatch,
        role=TenantMembership.Role.OWNER,
        uid_suffix="owner-conflict",
    )
    UserProfile.objects.create(
        firebase_uid="uid-existing",
        email="existing@example.com",
    )

    response = client.post(
        "/t/tenant-a/api/v1/team",
        data={
            "email": "existing@example.com",
            "firebase_uid": "uid-different",
            "role": TenantMembership.Role.ADMIN,
        },
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400

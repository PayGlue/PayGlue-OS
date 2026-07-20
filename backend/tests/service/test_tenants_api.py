from dataclasses import dataclass

import pytest
from django.test import Client

from payglue_backend.tenants.models import BillingAccount, Tenant, TenantMembership, UserProfile


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


def _auth_headers(
    monkeypatch: pytest.MonkeyPatch,
    firebase_uid: str,
    email: str,
) -> dict[str, str]:
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(_StubClaims(firebase_uid=firebase_uid, email=email)),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


def test_tenants_api_requires_bearer_auth() -> None:
    client = Client()

    list_response = client.get("/api/v1/tenants")
    create_response = client.post(
        "/api/v1/tenants",
        data={"slug": "acme"},
        content_type="application/json",
    )

    assert list_response.status_code == 401
    assert create_response.status_code == 401


def test_tenants_api_rejects_uninvited_stranger_instead_of_provisioning_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A verified JWT for an email that was never invited (no UserProfile, no
    # InvitationGrant) must be rejected, not silently given a bare profile --
    # this is exactly the gap that would let anyone with a valid Supabase
    # OAuth login (Google/GitHub) bypass the invite gate entirely.
    client = Client()
    headers = _auth_headers(monkeypatch, "uid-stranger", "stranger@example.com")

    response = client.post(
        "/api/v1/tenants",
        data={"slug": "stranger-team"},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 401
    assert not UserProfile.objects.filter(firebase_uid="uid-stranger").exists()
    assert not Tenant.objects.filter(slug="stranger-team").exists()


def test_tenants_api_lists_active_memberships_for_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    profile = UserProfile.objects.create(
        firebase_uid="uid-list", email="list@example.com"
    )
    active_tenant = Tenant.objects.create(slug="tenant-live", schema_name="tenant_live")
    suspended_tenant = Tenant.objects.create(
        slug="tenant-paused",
        schema_name="tenant_paused",
        status=Tenant.Status.SUSPENDED,
    )
    TenantMembership.objects.create(
        tenant=active_tenant,
        user_profile=profile,
        role=TenantMembership.Role.ADMIN,
    )
    TenantMembership.objects.create(
        tenant=suspended_tenant,
        user_profile=profile,
        role=TenantMembership.Role.OWNER,
    )

    headers = _auth_headers(monkeypatch, "uid-list", "list@example.com")

    response = client.get("/api/v1/tenants", **headers)

    assert response.status_code == 200
    assert response.json() == [{"tenant_slug": "tenant-live", "role": "admin"}]


def test_tenants_api_creates_tenant_and_owner_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    UserProfile.objects.create(firebase_uid="uid-create", email="create@example.com")
    headers = _auth_headers(monkeypatch, "uid-create", "create@example.com")

    response = client.post(
        "/api/v1/tenants",
        data={"slug": "acme-team"},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 201
    assert response.json() == {"tenant_slug": "acme-team", "role": "owner"}
    tenant = Tenant.objects.get(slug="acme-team")
    assert tenant.schema_name == "acme_team"
    membership = TenantMembership.objects.get(tenant=tenant)
    assert membership.role == TenantMembership.Role.OWNER
    assert membership.user_profile.firebase_uid == "uid-create"
    # Found live (PG-141 test): nothing else in the codebase ever created one
    # of these, so every tenant made through the real signup flow had
    # billing_account=None -- silently exempt from plan enforcement and with
    # nothing for the dashboard's plan/usage cards to read.
    assert tenant.billing_account is not None
    assert tenant.billing_account.plan.key == "founding"


def test_tenants_api_second_tenant_reuses_owners_billing_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    UserProfile.objects.create(firebase_uid="uid-second", email="second@example.com")
    headers = _auth_headers(monkeypatch, "uid-second", "second@example.com")

    client.post(
        "/api/v1/tenants", data={"slug": "first-pub"}, content_type="application/json", **headers
    )
    client.post(
        "/api/v1/tenants", data={"slug": "second-pub"}, content_type="application/json", **headers
    )

    first = Tenant.objects.get(slug="first-pub")
    second = Tenant.objects.get(slug="second-pub")
    assert first.billing_account_id == second.billing_account_id
    assert BillingAccount.objects.filter(owner__firebase_uid="uid-second").count() == 1


def test_tenants_api_returns_clean_error_for_duplicate_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    Tenant.objects.create(slug="acme", schema_name="acme")
    UserProfile.objects.create(firebase_uid="uid-dupe", email="dupe@example.com")
    headers = _auth_headers(monkeypatch, "uid-dupe", "dupe@example.com")

    response = client.post(
        "/api/v1/tenants",
        data={"slug": "acme"},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400
    assert response.json() == {"slug": ["Tenant slug already exists."]}

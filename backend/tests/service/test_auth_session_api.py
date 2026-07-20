from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from payglue_backend.authn import verifier
from payglue_backend.tenants.models import (
    BillingAccount,
    InvitationGrant,
    Plan,
    Tenant,
    TenantMembership,
    UserProfile,
)


pytestmark = pytest.mark.django_db


class _StubVerifier:
    def __init__(self, claims: verifier.VerifiedTokenClaims) -> None:
        self._claims = claims

    def verify(self, token: str) -> verifier.VerifiedTokenClaims:
        del token
        return self._claims


def test_auth_session_rejects_missing_authorization_header() -> None:
    client = Client()

    response = client.post("/api/v1/auth/session")

    assert response.status_code == 401


def test_auth_session_rejects_malformed_bearer_token() -> None:
    client = Client()

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer malformed-token",
    )

    assert response.status_code == 401


def test_auth_session_rejects_invalid_verified_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()

    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _InvalidTokenVerifier(),
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 401


def test_auth_session_returns_503_when_verifier_backend_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()

    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _UnavailableVerifier(),
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 503


def test_auth_session_returns_user_and_active_memberships_for_valid_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    active_tenant = Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")
    Tenant.objects.create(
        slug="tenant-inactive",
        schema_name="tenant_inactive",
        status=Tenant.Status.DISABLED,
    )

    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _StubVerifier(
            verifier.VerifiedTokenClaims(
                firebase_uid="uid_123",
                email="stub-user@example.com",
            )
        ),
    )

    profile = UserProfile.objects.create(
        firebase_uid="uid_123",
        email="old-email@example.com",
    )
    TenantMembership.objects.create(
        tenant=active_tenant,
        user_profile=profile,
        role=TenantMembership.Role.ADMIN,
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["firebase_uid"] == "uid_123"
    assert payload["user"]["email"] == "stub-user@example.com"
    assert payload["memberships"] == [
        {"tenant_slug": "tenant-a", "role": "admin", "status": "active"}
    ]
    assert payload["billing"] is None

    profile.refresh_from_db()
    assert profile.email == "stub-user@example.com"


def test_auth_session_excludes_inactive_tenant_memberships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    active_tenant = Tenant.objects.create(slug="tenant-live", schema_name="tenant_live")
    inactive_tenant = Tenant.objects.create(
        slug="tenant-suspended",
        schema_name="tenant_suspended",
        status=Tenant.Status.SUSPENDED,
    )
    profile = UserProfile.objects.create(
        firebase_uid="uid_777",
        email="uid777@example.com",
    )
    TenantMembership.objects.create(
        tenant=active_tenant,
        user_profile=profile,
        role=TenantMembership.Role.OWNER,
    )
    TenantMembership.objects.create(
        tenant=inactive_tenant,
        user_profile=profile,
        role=TenantMembership.Role.ADMIN,
    )

    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _StubVerifier(
            verifier.VerifiedTokenClaims(
                firebase_uid="uid_777",
                email="uid777@example.com",
            )
        ),
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 200
    assert response.json()["memberships"] == [
        {"tenant_slug": "tenant-live", "role": "owner", "status": "active"}
    ]


def test_auth_session_includes_paused_tenant_memberships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    paused_tenant = Tenant.objects.create(
        slug="tenant-paused", schema_name="tenant_paused", status=Tenant.Status.PAUSED
    )
    profile = UserProfile.objects.create(firebase_uid="uid_paused", email="paused@example.com")
    TenantMembership.objects.create(
        tenant=paused_tenant, user_profile=profile, role=TenantMembership.Role.OWNER
    )

    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _StubVerifier(
            verifier.VerifiedTokenClaims(firebase_uid="uid_paused", email="paused@example.com")
        ),
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 200
    assert response.json()["memberships"] == [
        {"tenant_slug": "tenant-paused", "role": "owner", "status": "paused"}
    ]


def test_auth_session_returns_grace_period_info_when_downgrade_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    solo = Plan.objects.get(key="solo")
    profile = UserProfile.objects.create(firebase_uid="uid_grace", email="grace@example.com")
    downgrade_at = timezone.now() - timedelta(days=5)
    BillingAccount.objects.create(owner=profile, plan=solo, downgrade_detected_at=downgrade_at)

    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _StubVerifier(
            verifier.VerifiedTokenClaims(firebase_uid="uid_grace", email="grace@example.com")
        ),
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 200
    billing = response.json()["billing"]
    assert billing["plan"] == "solo"
    assert billing["downgrade_detected_at"] is not None
    assert billing["grace_period_ends_at"] is not None


def test_auth_session_billing_has_no_grace_period_when_no_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    solo = Plan.objects.get(key="solo")
    profile = UserProfile.objects.create(firebase_uid="uid_nograce", email="nograce@example.com")
    BillingAccount.objects.create(owner=profile, plan=solo)

    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _StubVerifier(
            verifier.VerifiedTokenClaims(firebase_uid="uid_nograce", email="nograce@example.com")
        ),
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 200
    billing = response.json()["billing"]
    assert billing["plan"] == "solo"
    assert billing["downgrade_detected_at"] is None
    assert billing["grace_period_ends_at"] is None


def test_auth_session_accepts_lowercase_bearer_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    InvitationGrant.objects.create(email="user321@example.com")
    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _StubVerifier(
            verifier.VerifiedTokenClaims(
                firebase_uid="uid_321",
                email="user321@example.com",
            )
        ),
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="bearer stub.header.signature",
    )

    assert response.status_code == 200


def test_auth_session_rejects_new_user_without_validated_invite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()

    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _StubVerifier(
            verifier.VerifiedTokenClaims(
                firebase_uid="uid_new",
                email="new-user@example.com",
            )
        ),
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 403


def test_auth_session_creates_profile_when_invite_grant_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()

    InvitationGrant.objects.create(email="new-user@example.com")

    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _StubVerifier(
            verifier.VerifiedTokenClaims(
                firebase_uid="uid_new",
                email="new-user@example.com",
            )
        ),
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 200
    profile = UserProfile.objects.get(firebase_uid="uid_new")
    assert profile.email == "new-user@example.com"
    grant = InvitationGrant.objects.get(email="new-user@example.com")
    assert grant.consumed_at is not None


def test_auth_session_links_existing_email_profile_to_new_firebase_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()

    profile = UserProfile.objects.create(
        firebase_uid="uid_old",
        email="existing@example.com",
    )

    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _StubVerifier(
            verifier.VerifiedTokenClaims(
                firebase_uid="uid_new",
                email="existing@example.com",
            )
        ),
    )

    response = client.post(
        "/api/v1/auth/session",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 200
    profile.refresh_from_db()
    assert profile.firebase_uid == "uid_new"


class _InvalidTokenVerifier:
    def verify(self, token: str) -> verifier.VerifiedTokenClaims:
        del token
        raise verifier.InvalidAuthTokenError


class _UnavailableVerifier:
    def verify(self, token: str) -> verifier.VerifiedTokenClaims:
        del token
        raise verifier.AuthVerificationUnavailableError

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
) -> dict[str, str]:
    tenant = Tenant.objects.get(slug="tenant-a")
    profile = UserProfile.objects.create(
        firebase_uid=f"uid-{uid_suffix}",
        email=f"{uid_suffix}@example.com",
    )
    TenantMembership.objects.create(
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
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


@pytest.mark.parametrize(
    ("role", "can_write"),
    [
        (TenantMembership.Role.OWNER, True),
        (TenantMembership.Role.ADMIN, False),
        (TenantMembership.Role.BILLING_ADMIN, True),
        (TenantMembership.Role.SUPPORT_READONLY, False),
    ],
)
def test_billing_api_permission_matrix(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    can_write: bool,
) -> None:
    client = Client()
    headers = _auth_headers(
        monkeypatch,
        role=role,
        uid_suffix=f"billing-{role}",
    )

    get_response = client.get("/t/tenant-a/api/v1/billing", **headers)
    assert get_response.status_code == 200

    put_response = client.put(
        "/t/tenant-a/api/v1/billing",
        data={
            "legal_name": "Acme GmbH",
            "billing_email": "finance@example.com",
            "country_code": "DE",
            "tax_id": "DE123456789",
        },
        content_type="application/json",
        **headers,
    )
    assert put_response.status_code == (200 if can_write else 403)


def test_billing_api_rejects_unknown_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()
    headers = _auth_headers(
        monkeypatch,
        role=TenantMembership.Role.OWNER,
        uid_suffix="billing-owner",
    )

    response = client.put(
        "/t/tenant-a/api/v1/billing",
        data={"legal_name": "Acme", "secret_note": "must-fail"},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400

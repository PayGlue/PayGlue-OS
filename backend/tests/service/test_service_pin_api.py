import re
from dataclasses import dataclass

import pytest
from django.test import Client

from payglue_backend.tenants.models import ServicePin, Tenant, TenantMembership, UserProfile


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
    ("role", "allowed"),
    [
        (TenantMembership.Role.OWNER, True),
        (TenantMembership.Role.ADMIN, True),
        (TenantMembership.Role.BILLING_ADMIN, False),
        (TenantMembership.Role.SUPPORT_READONLY, False),
    ],
)
def test_service_pin_api_permission_matrix(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    allowed: bool,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, role=role, uid_suffix=f"pin-{role}")

    get_response = client.get("/t/tenant-a/api/v1/service-pin", **headers)
    assert get_response.status_code == (200 if allowed else 403)

    post_response = client.post("/t/tenant-a/api/v1/service-pin", **headers)
    assert post_response.status_code == (201 if allowed else 403)


def test_service_pin_generate_returns_expected_format(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, role=TenantMembership.Role.OWNER, uid_suffix="pin-owner")

    response = client.post("/t/tenant-a/api/v1/service-pin", **headers)

    assert response.status_code == 201
    body = response.json()["pin"]
    assert re.fullmatch(r"PGS-\d{5}", body["code"])
    assert body["revoked_at"] is None


def test_service_pin_generate_revokes_prior_active_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, role=TenantMembership.Role.OWNER, uid_suffix="pin-owner")

    first = client.post("/t/tenant-a/api/v1/service-pin", **headers).json()["pin"]
    second = client.post("/t/tenant-a/api/v1/service-pin", **headers).json()["pin"]

    assert first["code"] != second["code"]
    first_pin = ServicePin.objects.get(code=first["code"])
    assert first_pin.revoked_at is not None

    get_response = client.get("/t/tenant-a/api/v1/service-pin", **headers)
    assert get_response.json()["pin"]["code"] == second["code"]


def test_service_pin_get_returns_null_when_none_active(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, role=TenantMembership.Role.OWNER, uid_suffix="pin-owner")

    response = client.get("/t/tenant-a/api/v1/service-pin", **headers)

    assert response.status_code == 200
    assert response.json()["pin"] is None


def test_service_pin_delete_revokes_active_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, role=TenantMembership.Role.OWNER, uid_suffix="pin-owner")
    client.post("/t/tenant-a/api/v1/service-pin", **headers)

    delete_response = client.delete("/t/tenant-a/api/v1/service-pin", **headers)
    assert delete_response.status_code == 204

    get_response = client.get("/t/tenant-a/api/v1/service-pin", **headers)
    assert get_response.json()["pin"] is None

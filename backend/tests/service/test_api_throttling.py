from dataclasses import dataclass

import pytest
from django.core.cache import cache
from django.test import Client, override_settings

from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile
from payglue_backend.webhooks.models import IntegrationConfig


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


class _CapturingCredentialProvider:
    def get_credentials(self, tenant_ctx, provider_key):  # pragma: no cover - unused
        del tenant_ctx, provider_key
        return {}

    def set_credentials(
        self, tenant_ctx, provider_key: str, credentials: dict[str, str]
    ):
        del credentials
        return {
            "backend": "memory",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "masked_keys": [provider_key, tenant_ctx.tenant_slug],
        }


@pytest.fixture(autouse=True)
def _seed_tenant_registry() -> None:
    Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")
    Tenant.objects.create(slug="tenant-b", schema_name="tenant_b")


@pytest.fixture(autouse=True)
def _clear_throttle_cache() -> None:
    cache.clear()


def _auth_headers(monkeypatch: pytest.MonkeyPatch, role: str) -> dict[str, str]:
    profile = UserProfile.objects.create(
        firebase_uid=f"uid-{role}",
        email=f"{role}@example.com",
    )
    tenant = Tenant.objects.get(slug="tenant-a")
    TenantMembership.objects.create(tenant=tenant, user_profile=profile, role=role)
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(
            _StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)
        ),
    )
    monkeypatch.setattr(
        "payglue_backend.authn.views.get_auth_token_verifier",
        lambda: _StubVerifier(
            _StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)
        ),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_CLASSES": [
            "payglue_backend.http.throttling.DynamicScopedRateThrottle"
        ],
        "DEFAULT_THROTTLE_RATES": {
            "auth_session": "1/minute",
            "webhook_ingest": "1/minute",
            "integration_credentials_write": "1/minute",
            "integration_health": "1/minute",
        },
    }
)
def test_auth_session_endpoint_is_throttled() -> None:
    client = Client()

    first = client.post("/api/v1/auth/session")
    second = client.post("/api/v1/auth/session")

    assert first.status_code == 401
    assert second.status_code == 429


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_CLASSES": [
            "payglue_backend.http.throttling.DynamicScopedRateThrottle"
        ],
        "DEFAULT_THROTTLE_RATES": {
            "auth_session": "1/minute",
            "webhook_ingest": "1/minute",
            "integration_credentials_write": "1/minute",
            "integration_health": "1/minute",
        },
    }
)
def test_webhook_ingest_endpoint_is_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.validate_endpoint_token",
        lambda tenant_slug, provider, endpoint_token: True,
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.tasks.process_inbound_webhook_event.delay",
        lambda event_id, **kwargs: None,
    )
    client = Client()

    first = client.post(
        "/t/tenant-a/webhooks/polar/endpoint-token/",
        data=b"{}",
        content_type="application/json",
    )
    second = client.post(
        "/t/tenant-a/webhooks/polar/endpoint-token/",
        data=b"{}",
        content_type="application/json",
    )

    assert first.status_code == 202
    assert second.status_code == 429


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_CLASSES": [
            "payglue_backend.http.throttling.DynamicScopedRateThrottle"
        ],
        "DEFAULT_THROTTLE_RATES": {
            "auth_session": "1/minute",
            "webhook_ingest": "1/minute",
            "integration_credentials_write": "1/minute",
            "integration_health": "1/minute",
        },
    }
)
def test_webhook_ingest_throttle_is_tenant_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.validate_endpoint_token",
        lambda tenant_slug, provider, endpoint_token: True,
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.tasks.process_inbound_webhook_event.delay",
        lambda event_id, **kwargs: None,
    )
    client = Client()

    tenant_a = client.post(
        "/t/tenant-a/webhooks/polar/endpoint-token/",
        data=b"{}",
        content_type="application/json",
    )
    tenant_b = client.post(
        "/t/tenant-b/webhooks/polar/endpoint-token/",
        data=b"{}",
        content_type="application/json",
    )

    assert tenant_a.status_code == 202
    assert tenant_b.status_code == 202


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_THROTTLE_CLASSES": [
            "payglue_backend.http.throttling.DynamicScopedRateThrottle"
        ],
        "DEFAULT_THROTTLE_RATES": {
            "auth_session": "1/minute",
            "webhook_ingest": "1/minute",
            "integration_credentials_write": "1/minute",
            "integration_health": "1/minute",
        },
    }
)
def test_integration_credentials_put_is_throttled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="cms",
        enabled=True,
        provider_type="ghost",
        metadata={},
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_credential_provider",
        lambda: _CapturingCredentialProvider(),
    )

    first = client.put(
        "/t/tenant-a/api/v1/integrations/cms/credentials",
        data={"credentials": {"admin_api_key": "id:secret"}},
        content_type="application/json",
        **headers,
    )
    second = client.put(
        "/t/tenant-a/api/v1/integrations/cms/credentials",
        data={"credentials": {"admin_api_key": "id:secret"}},
        content_type="application/json",
        **headers,
    )

    assert first.status_code == 200
    assert second.status_code == 429

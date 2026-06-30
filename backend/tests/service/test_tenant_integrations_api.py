from dataclasses import dataclass

import pytest
from django.test import Client
from django.utils import timezone

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


@pytest.fixture(autouse=True)
def _seed_tenant_registry() -> None:
    Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")


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
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


def test_integration_config_get_put_and_mappings_crud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    owner = UserProfile.objects.create(
        firebase_uid="uid-owner", email="owner@example.com"
    )
    tenant = Tenant.objects.get(slug="tenant-a")
    TenantMembership.objects.create(
        tenant=tenant,
        user_profile=owner,
        role=TenantMembership.Role.OWNER,
    )

    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(
            _StubClaims(firebase_uid=owner.firebase_uid, email=owner.email)
        ),
    )

    headers = {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}

    get_missing = client.get("/t/tenant-a/api/v1/integrations/cms", **headers)
    assert get_missing.status_code == 404

    put_response = client.put(
        "/t/tenant-a/api/v1/integrations/cms",
        data={
            "enabled": True,
            "provider_type": "ghost",
            "metadata": {"site_url": "https://ghost.example.com"},
        },
        content_type="application/json",
        **headers,
    )
    assert put_response.status_code == 200
    assert put_response.json()["provider_key"] == "cms"

    get_response = client.get("/t/tenant-a/api/v1/integrations/cms", **headers)
    assert get_response.status_code == 200
    assert get_response.json()["metadata"] == {"site_url": "https://ghost.example.com"}

    post_mapping = client.post(
        "/t/tenant-a/api/v1/mappings",
        data={
            "payment_provider": "polar",
            "event_type": "order.paid",
            "external_product_id": "prod_basic",
            "entitlement_key": "tier.basic",
            "action": "grant",
            "quantity": 2,
            "is_active": True,
        },
        content_type="application/json",
        **headers,
    )
    assert post_mapping.status_code == 201
    mapping_id = post_mapping.json()["id"]

    list_response = client.get("/t/tenant-a/api/v1/mappings", **headers)
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    delete_response = client.delete(
        f"/t/tenant-a/api/v1/mappings?mapping_id={mapping_id}",
        **headers,
    )
    assert delete_response.status_code == 204


@pytest.mark.parametrize(
    ("role", "can_write"),
    [
        (TenantMembership.Role.OWNER, True),
        (TenantMembership.Role.ADMIN, True),
        (TenantMembership.Role.BILLING_ADMIN, False),
        (TenantMembership.Role.SUPPORT_READONLY, False),
    ],
)
def test_integration_api_permission_matrix(
    monkeypatch: pytest.MonkeyPatch, role: str, can_write: bool
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, role)

    put_response = client.put(
        "/t/tenant-a/api/v1/integrations/payment",
        data={
            "enabled": True,
            "provider_type": "polar",
            "metadata": {"region": "eu"},
        },
        content_type="application/json",
        **headers,
    )
    assert put_response.status_code == (200 if can_write else 403)

    get_response = client.get("/t/tenant-a/api/v1/integrations/payment", **headers)
    assert get_response.status_code in {200, 404}


def test_tenant_integration_requires_bearer_auth() -> None:
    client = Client()

    response = client.get("/t/tenant-a/api/v1/integrations/payment")

    assert response.status_code == 401


def test_integration_config_rejects_unsupported_provider_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)

    response = client.put(
        "/t/tenant-a/api/v1/integrations/cms",
        data={
            "enabled": True,
            "provider_type": "not-real-cms",
            "metadata": {},
        },
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400


def test_product_mapping_rejects_unsupported_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)

    response = client.post(
        "/t/tenant-a/api/v1/mappings",
        data={
            "payment_provider": "polar",
            "event_type": "order.paid",
            "external_product_id": "prod_basic",
            "entitlement_key": "tier.basic",
            "action": "unknown",
            "quantity": 1,
            "is_active": True,
        },
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400


def test_product_mapping_rejects_unsupported_payment_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)

    response = client.post(
        "/t/tenant-a/api/v1/mappings",
        data={
            "payment_provider": "unknownpay",
            "event_type": "order.paid",
            "external_product_id": "prod_basic",
            "entitlement_key": "tier.basic",
            "action": "grant",
            "quantity": 1,
            "is_active": True,
        },
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400


def test_integration_put_invalid_payload_does_not_create_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)

    response = client.put(
        "/t/tenant-a/api/v1/integrations/cms",
        data={
            "enabled": True,
            "provider_type": "unsupported-cms",
            "metadata": {},
        },
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400
    assert (
        IntegrationConfig.objects.filter(
            tenant_slug="tenant-a", provider_key="cms"
        ).count()
        == 0
    )


class _CapturingCredentialProvider:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str, dict[str, str]]] = []

    def get_credentials(self, tenant_ctx, provider_key):  # pragma: no cover - unused
        del tenant_ctx, provider_key
        return {}

    def set_credentials(
        self, tenant_ctx, provider_key: str, credentials: dict[str, str]
    ) -> dict[str, object]:
        self.writes.append((tenant_ctx.tenant_slug, provider_key, dict(credentials)))
        return {
            "backend": "firestore",
            "document_path": f"tenant_provider_credentials/{tenant_ctx.tenant_slug}--{provider_key}",
            "updated_at": timezone.now().isoformat(),
            "masked_keys": sorted(credentials.keys()),
        }


@pytest.mark.parametrize(
    ("role", "can_write"),
    [
        (TenantMembership.Role.OWNER, True),
        (TenantMembership.Role.ADMIN, True),
        (TenantMembership.Role.BILLING_ADMIN, False),
        (TenantMembership.Role.SUPPORT_READONLY, False),
    ],
)
def test_integration_credentials_api_permission_matrix(
    monkeypatch: pytest.MonkeyPatch, role: str, can_write: bool
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, role)
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="cms",
        enabled=True,
        provider_type="ghost",
        metadata={"site_url": "https://ghost.example.com"},
    )
    provider = _CapturingCredentialProvider()
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_credential_provider",
        lambda: provider,
    )

    response = client.put(
        "/t/tenant-a/api/v1/integrations/cms/credentials",
        data={
            "credentials": {"admin_api_key": "id:secret", "api_base_url": "https://api"}
        },
        content_type="application/json",
        **headers,
    )

    assert response.status_code == (200 if can_write else 403)
    assert len(provider.writes) == (1 if can_write else 0)


def test_integration_credentials_put_stores_and_redacts_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="cms",
        enabled=True,
        provider_type="ghost",
        metadata={"site_url": "https://ghost.example.com"},
    )
    provider = _CapturingCredentialProvider()
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_credential_provider",
        lambda: provider,
    )

    response = client.put(
        "/t/tenant-a/api/v1/integrations/cms/credentials",
        data={
            "credentials": {
                "admin_api_key": "id:super-secret",
                "api_base_url": "https://ghost-admin.example.com",
            }
        },
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_key"] == "cms"
    assert body["provider_type"] == "ghost"
    assert body["credential_ref"]["backend"] == "firestore"
    assert body["credential_ref"]["masked_keys"] == ["admin_api_key", "api_base_url"]
    assert "document_path" not in body["credential_ref"]
    assert "super-secret" not in str(body)

    integration = IntegrationConfig.objects.get(
        tenant_slug="tenant-a", provider_key="cms"
    )
    assert integration.metadata["site_url"] == "https://ghost.example.com"
    assert integration.metadata["credential_ref"]["backend"] == "firestore"
    assert integration.metadata["credential_ref"]["masked_keys"] == [
        "admin_api_key",
        "api_base_url",
    ]
    assert "document_path" not in integration.metadata["credential_ref"]
    assert "super-secret" not in str(integration.metadata)


def test_integration_credentials_put_requires_existing_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_credential_provider",
        lambda: _CapturingCredentialProvider(),
    )

    response = client.put(
        "/t/tenant-a/api/v1/integrations/cms/credentials",
        data={"credentials": {"admin_api_key": "id:secret"}},
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 404


def test_integration_health_check_for_ghost_updates_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _HealthyGhostAdapter:
        def health_check(self, tenant_ctx):
            assert tenant_ctx.tenant_slug == "tenant-a"
            return {"ok": True, "code": "ok", "message": "ghost is reachable"}

    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="cms",
        enabled=True,
        provider_type="ghost",
        metadata={"site_url": "https://ghost.example.com"},
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.views.wiring.get_cms_adapter",
        lambda provider_key: _HealthyGhostAdapter(),
    )

    response = client.get("/t/tenant-a/api/v1/integrations/cms/health", **headers)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["code"] == "ok"
    assert body["message"] == "ghost is reachable"
    assert isinstance(body["checked_at"], str)

    integration = IntegrationConfig.objects.get(
        tenant_slug="tenant-a", provider_key="cms"
    )
    assert integration.metadata["site_url"] == "https://ghost.example.com"
    assert integration.metadata["health"]["ok"] is True
    assert integration.metadata["health"]["code"] == "ok"
    assert integration.metadata["health"]["message"] == "ghost is reachable"
    assert isinstance(integration.metadata["health"]["checked_at"], str)


def test_integration_health_forbids_support_readonly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.SUPPORT_READONLY)
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="cms",
        enabled=True,
        provider_type="ghost",
        metadata={},
    )

    response = client.get("/t/tenant-a/api/v1/integrations/cms/health", **headers)

    assert response.status_code == 403


def test_integration_health_requires_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    profile = UserProfile.objects.create(
        firebase_uid="uid-outsider", email="outsider@example.com"
    )
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(
            _StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)
        ),
    )
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="cms",
        enabled=True,
        provider_type="ghost",
        metadata={},
    )

    response = client.get(
        "/t/tenant-a/api/v1/integrations/cms/health",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 403


def test_integration_health_returns_404_when_config_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)

    response = client.get("/t/tenant-a/api/v1/integrations/cms/health", **headers)

    assert response.status_code == 404


def test_integration_health_returns_400_when_integration_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="cms",
        enabled=False,
        provider_type="ghost",
        metadata={},
    )

    response = client.get("/t/tenant-a/api/v1/integrations/cms/health", **headers)

    assert response.status_code == 400
    assert "disabled" in response.json()["detail"].lower()


def test_integration_health_for_payment_updates_metadata_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _HealthyPaymentAdapter:
        def health_check(self, tenant_ctx):
            assert tenant_ctx.tenant_slug == "tenant-a"
            return {
                "ok": True,
                "code": "ok",
                "message": "polar credentials validated",
            }

    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="payment",
        enabled=True,
        provider_type="polar",
        metadata={},
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.views.wiring.get_payment_adapter",
        lambda provider_key: _HealthyPaymentAdapter(),
    )

    response = client.get("/t/tenant-a/api/v1/integrations/payment/health", **headers)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["code"] == "ok"
    assert body["message"] == "polar credentials validated"
    assert isinstance(body["checked_at"], str)

    integration = IntegrationConfig.objects.get(
        tenant_slug="tenant-a", provider_key="payment"
    )
    assert integration.metadata["health"]["ok"] is True
    assert integration.metadata["health"]["code"] == "ok"
    assert integration.metadata["health"]["message"] == "polar credentials validated"
    assert isinstance(integration.metadata["health"]["checked_at"], str)


def test_integration_health_for_payment_updates_metadata_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingPaymentAdapter:
        def health_check(self, tenant_ctx):
            del tenant_ctx
            raise RuntimeError("unavailable")

    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="payment",
        enabled=True,
        provider_type="polar",
        metadata={"region": "eu"},
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.views.wiring.get_payment_adapter",
        lambda provider_key: _FailingPaymentAdapter(),
    )

    response = client.get("/t/tenant-a/api/v1/integrations/payment/health", **headers)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "error"
    assert "failed" in body["message"].lower()

    integration = IntegrationConfig.objects.get(
        tenant_slug="tenant-a", provider_key="payment"
    )
    assert integration.metadata["region"] == "eu"
    assert integration.metadata["health"]["ok"] is False
    assert integration.metadata["health"]["code"] == "error"

from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from payglue_backend.tenants.models import (
    PublicAuditEvent,
    Tenant,
    TenantMembership,
    UserProfile,
)
from payglue_backend.webhooks.models import IntegrationConfig, WebhookInboundEvent


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
    Tenant.objects.create(slug="tenant-b", schema_name="tenant_b")


def _auth_headers(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenant_slug: str = "tenant-a",
    role: str = TenantMembership.Role.OWNER,
    uid_suffix: str = "owner",
) -> dict[str, str]:
    tenant = Tenant.objects.get(slug=tenant_slug)
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


def test_team_and_billing_mutations_emit_audit_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch)
    invitee = UserProfile.objects.create(
        firebase_uid="uid-invitee",
        email="invitee@example.com",
    )

    create_response = client.post(
        "/t/tenant-a/api/v1/team",
        data={"email": invitee.email, "role": TenantMembership.Role.ADMIN},
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 201
    membership_id = create_response.json()["id"]

    update_response = client.patch(
        f"/t/tenant-a/api/v1/team/{membership_id}",
        data={"role": TenantMembership.Role.BILLING_ADMIN},
        content_type="application/json",
        **headers,
    )
    assert update_response.status_code == 200

    delete_response = client.delete(
        f"/t/tenant-a/api/v1/team/{membership_id}", **headers
    )
    assert delete_response.status_code == 204

    billing_response = client.put(
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
    assert billing_response.status_code == 200

    event_types = list(
        PublicAuditEvent.objects.filter(tenant__slug="tenant-a")
        .order_by("id")
        .values_list("event_type", flat=True)
    )
    assert event_types == [
        PublicAuditEvent.EventType.TEAM_MEMBER_CREATED,
        PublicAuditEvent.EventType.TEAM_MEMBER_ROLE_UPDATED,
        PublicAuditEvent.EventType.TEAM_MEMBER_REMOVED,
        PublicAuditEvent.EventType.BILLING_PROFILE_UPDATED,
    ]


class _CapturingCredentialProvider:
    def get_credentials(self, tenant_ctx, provider_key):  # pragma: no cover - unused
        del tenant_ctx, provider_key
        return {}

    def set_credentials(
        self, tenant_ctx, provider_key: str, credentials: dict[str, str]
    ):
        del credentials
        return {
            "backend": "firestore",
            "provider_key": provider_key,
            "tenant_slug": tenant_ctx.tenant_slug,
            "updated_at": "2026-01-01T00:00:00+00:00",
            "masked_keys": ["admin_api_key"],
            "document_path": "tenant_provider_credentials/tenant-a--cms",
        }


def test_sensitive_mutations_emit_safe_audit_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch)
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="cms",
        enabled=True,
        provider_type="ghost",
        metadata={"site_url": "https://ghost.example.com"},
    )
    replay_event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.FAILED,
        payload_raw=b"{}",
        payload_snapshot={},
        headers_snapshot={"Content-Type": "application/json"},
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
        endpoint_token_hash="hash",
        endpoint_metadata={"method": "POST"},
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_credential_provider",
        lambda: _CapturingCredentialProvider(),
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.views.process_inbound_webhook_event.delay",
        lambda event_id, **kwargs: None,
    )

    credential_response = client.put(
        "/t/tenant-a/api/v1/integrations/cms/credentials",
        data={"credentials": {"admin_api_key": "id:super-secret"}},
        content_type="application/json",
        **headers,
    )
    assert credential_response.status_code == 200

    replay_response = client.post(
        f"/t/tenant-a/api/v1/events/{replay_event.id}/replay",
        **headers,
    )
    assert replay_response.status_code == 202

    credential_audit = PublicAuditEvent.objects.get(
        tenant__slug="tenant-a",
        event_type=PublicAuditEvent.EventType.INTEGRATION_CREDENTIALS_WRITTEN,
    )
    replay_audit = PublicAuditEvent.objects.get(
        tenant__slug="tenant-a",
        event_type=PublicAuditEvent.EventType.EVENT_REPLAY_REQUESTED,
    )
    assert "super-secret" not in str(credential_audit.metadata)
    assert "document_path" not in str(credential_audit.metadata)
    assert replay_audit.metadata["event_id"] == replay_event.id


def test_audit_events_read_requires_tenant_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    outsider = UserProfile.objects.create(
        firebase_uid="uid-outsider",
        email="outsider@example.com",
    )
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(
            _StubClaims(firebase_uid=outsider.firebase_uid, email=outsider.email)
        ),
    )

    response = client.get(
        "/t/tenant-a/api/v1/events/audit",
        HTTP_AUTHORIZATION="Bearer stub.header.signature",
    )

    assert response.status_code == 403


def test_audit_events_read_supports_filters_and_tenant_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(
        monkeypatch,
        tenant_slug="tenant-a",
        role=TenantMembership.Role.SUPPORT_READONLY,
        uid_suffix="auditor",
    )
    tenant_a = Tenant.objects.get(slug="tenant-a")
    tenant_b = Tenant.objects.get(slug="tenant-b")
    actor = TenantMembership.objects.get(
        tenant=tenant_a, user_profile__email="auditor@example.com"
    )

    old_event = PublicAuditEvent.objects.create(
        tenant=tenant_a,
        actor_membership=actor,
        event_type=PublicAuditEvent.EventType.TEAM_MEMBER_CREATED,
        target_type="membership",
        target_id="m-1",
        metadata={"safe": True},
    )
    matching_event = PublicAuditEvent.objects.create(
        tenant=tenant_a,
        actor_membership=actor,
        event_type=PublicAuditEvent.EventType.BILLING_PROFILE_UPDATED,
        target_type="billing_profile",
        target_id="bp-1",
        metadata={"updated_fields": ["billing_email"]},
    )
    PublicAuditEvent.objects.create(
        tenant=tenant_b,
        actor_membership=None,
        event_type=PublicAuditEvent.EventType.BILLING_PROFILE_UPDATED,
        target_type="billing_profile",
        target_id="bp-other",
        metadata={},
    )

    now = timezone.now()
    PublicAuditEvent.objects.filter(id=old_event.id).update(
        created_at=now - timedelta(days=2)
    )
    PublicAuditEvent.objects.filter(id=matching_event.id).update(
        created_at=now - timedelta(hours=1)
    )

    response = client.get(
        "/t/tenant-a/api/v1/events/audit",
        {
            "event_type": PublicAuditEvent.EventType.BILLING_PROFILE_UPDATED,
            "target_type": "billing_profile",
            "created_at_from": (now - timedelta(hours=2)).isoformat(),
            "created_at_to": now.isoformat(),
        },
        **headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == matching_event.id
    assert body[0]["event_type"] == PublicAuditEvent.EventType.BILLING_PROFILE_UPDATED
    assert body[0]["target_type"] == "billing_profile"
    assert body[0]["target_id"] == "bp-1"
    assert body[0]["actor_membership_id"] == actor.id
    assert "actor_membership" not in body[0]
    assert "tenant_id" not in body[0]

from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile
from payglue_backend.webhooks.models import WebhookInboundEvent


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
    *,
    tenant_slug: str,
    role: str,
    uid_suffix: str,
) -> dict[str, str]:
    tenant = Tenant.objects.get(slug=tenant_slug)
    profile = UserProfile.objects.create(
        firebase_uid=f"uid-{uid_suffix}",
        email=f"{uid_suffix}@example.com",
    )
    TenantMembership.objects.create(tenant=tenant, user_profile=profile, role=role)
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(
            _StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)
        ),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


@pytest.fixture(autouse=True)
def _seed_tenants() -> None:
    Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")
    Tenant.objects.create(slug="tenant-b", schema_name="tenant_b")


def test_events_list_is_tenant_scoped_and_returns_safe_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(
        monkeypatch,
        tenant_slug="tenant-a",
        role=TenantMembership.Role.BILLING_ADMIN,
        uid_suffix="events-list",
    )
    WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.FAILED,
        payload_raw=b'{"event":"a"}',
        payload_snapshot={"event": "a"},
        headers_snapshot={"Content-Type": "application/json"},
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
        endpoint_token_hash="hash-a",
        endpoint_metadata={"method": "POST"},
    )
    WebhookInboundEvent.objects.create(
        tenant_slug="tenant-b",
        provider="polar",
        status=WebhookInboundEvent.Status.DEAD_LETTER,
        payload_raw=b'{"event":"b"}',
        payload_snapshot={"event": "b"},
        headers_snapshot={"Content-Type": "application/json"},
        endpoint_path="/t/tenant-b/webhooks/polar/[redacted]/",
        endpoint_token_hash="hash-b",
        endpoint_metadata={"method": "POST"},
    )

    response = client.get("/t/tenant-a/api/v1/events", **headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["tenant_slug"] == "tenant-a"
    assert "payload_raw" not in body[0]
    assert "endpoint_token_hash" not in body[0]


@pytest.mark.parametrize(
    ("role", "can_replay"),
    [
        (TenantMembership.Role.OWNER, True),
        (TenantMembership.Role.ADMIN, True),
        (TenantMembership.Role.BILLING_ADMIN, False),
        (TenantMembership.Role.SUPPORT_READONLY, False),
    ],
)
def test_event_replay_permission_matrix(
    monkeypatch: pytest.MonkeyPatch, role: str, can_replay: bool
) -> None:
    client = Client()
    headers = _auth_headers(
        monkeypatch,
        tenant_slug="tenant-a",
        role=role,
        uid_suffix=f"replay-{role}",
    )
    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.FAILED,
        attempts=3,
        next_attempt_at=timezone.now() + timedelta(hours=1),
        last_error="upstream timeout",
        payload_raw=b"{}",
        payload_snapshot={},
        headers_snapshot={"Content-Type": "application/json"},
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
        endpoint_token_hash="hash",
        endpoint_metadata={"method": "POST"},
    )

    queued: list[tuple[int, bool, str | None]] = []

    def _capture_delay(
        event_id: int,
        ignore_timing: bool = False,
        **kwargs: object,
    ) -> None:
        tenant_slug = kwargs.get("tenant_slug")
        queued.append(
            (
                event_id,
                ignore_timing,
                tenant_slug if isinstance(tenant_slug, str) else None,
            )
        )

    monkeypatch.setattr(
        "payglue_backend.webhooks.views.process_inbound_webhook_event.delay",
        _capture_delay,
    )

    response = client.post(f"/t/tenant-a/api/v1/events/{event.id}/replay", **headers)

    assert response.status_code == (202 if can_replay else 403)
    event.refresh_from_db()
    if can_replay:
        assert event.status == WebhookInboundEvent.Status.RECEIVED
        assert event.attempts == 0
        assert event.next_attempt_at is None
        assert event.last_error == ""
        assert queued == [(event.id, True, "tenant-a")]
    else:
        assert event.status == WebhookInboundEvent.Status.FAILED
        assert queued == []


def test_event_replay_rejects_invalid_state_and_missing_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(
        monkeypatch,
        tenant_slug="tenant-a",
        role=TenantMembership.Role.OWNER,
        uid_suffix="replay-invalid",
    )
    invalid_state_event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.PROCESSED,
        payload_raw=b"{}",
        payload_snapshot={},
        headers_snapshot={"Content-Type": "application/json"},
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
        endpoint_token_hash="hash-processed",
        endpoint_metadata={"method": "POST"},
    )
    other_tenant_event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-b",
        provider="polar",
        status=WebhookInboundEvent.Status.FAILED,
        payload_raw=b"{}",
        payload_snapshot={},
        headers_snapshot={"Content-Type": "application/json"},
        endpoint_path="/t/tenant-b/webhooks/polar/[redacted]/",
        endpoint_token_hash="hash-other",
        endpoint_metadata={"method": "POST"},
    )

    invalid_state_response = client.post(
        f"/t/tenant-a/api/v1/events/{invalid_state_event.id}/replay",
        **headers,
    )
    assert invalid_state_response.status_code == 400

    missing_response = client.post("/t/tenant-a/api/v1/events/999999/replay", **headers)
    assert missing_response.status_code == 404

    cross_tenant_response = client.post(
        f"/t/tenant-a/api/v1/events/{other_tenant_event.id}/replay",
        **headers,
    )
    assert cross_tenant_response.status_code == 404


def test_event_replay_returns_503_when_queue_publish_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    headers = _auth_headers(
        monkeypatch,
        tenant_slug="tenant-a",
        role=TenantMembership.Role.OWNER,
        uid_suffix="replay-queue-fail",
    )
    event = WebhookInboundEvent.objects.create(
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

    def _raise_queue_error(
        event_id: int,
        ignore_timing: bool = False,
        **kwargs: object,
    ) -> None:
        del event_id, ignore_timing, kwargs
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "payglue_backend.webhooks.views.process_inbound_webhook_event.delay",
        _raise_queue_error,
    )

    response = client.post(f"/t/tenant-a/api/v1/events/{event.id}/replay", **headers)

    assert response.status_code == 503
    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.FAILED
    assert event.last_error == "queue publish failed"

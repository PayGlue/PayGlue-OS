import json

import pytest
from django.test import Client
from django.test import override_settings

from payglue_backend.tenants.models import Tenant
from payglue_backend.webhooks.models import WebhookInboundEvent


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed_tenant_registry() -> None:
    Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")


def test_webhook_ingest_returns_202_and_enqueues_event(monkeypatch) -> None:
    seen: list[tuple[int, str | None]] = []

    def _capture_delay(event_id: int, **kwargs: object) -> None:
        tenant_slug = kwargs.get("tenant_slug")
        seen.append((event_id, tenant_slug if isinstance(tenant_slug, str) else None))

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.validate_endpoint_token",
        lambda tenant_slug, provider, endpoint_token: True,
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.tasks.process_inbound_webhook_event.delay",
        _capture_delay,
    )
    client = Client()

    response = client.post(
        "/t/tenant-a/webhooks/polar/endpoint-token/",
        data=b'{"id":"evt_1"}',
        content_type="application/json",
        HTTP_X_TEST_HEADER="test-value",
    )

    assert response.status_code == 202
    tracking_id = response.json()["tracking_id"]
    event = WebhookInboundEvent.objects.get(id=tracking_id)
    assert response.json() == {
        "status": "accepted",
        "tracking_id": event.id,
    }
    assert event.status == WebhookInboundEvent.Status.RECEIVED
    assert event.tenant_slug == "tenant-a"
    assert event.provider == "polar"
    assert event.endpoint_path == "/t/tenant-a/webhooks/polar/[redacted]/"
    assert event.payload_raw == b'{"id":"evt_1"}'
    assert event.headers_snapshot.get("Content-Type") == "application/json"
    assert "Authorization" not in event.headers_snapshot
    assert seen == [(event.id, "tenant-a")]


def test_webhook_ingest_rejects_invalid_endpoint_token(monkeypatch) -> None:
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.validate_endpoint_token",
        lambda tenant_slug, provider, endpoint_token: False,
    )
    client = Client()

    response = client.post(
        "/t/tenant-a/webhooks/polar/bad-token/",
        data=b"{}",
        content_type="application/json",
    )

    assert response.status_code == 404
    assert WebhookInboundEvent.objects.count() == 0


def test_webhook_ingest_path_without_tenant_prefix_is_not_found() -> None:
    client = Client()

    response = client.post(
        "/webhooks/polar/endpoint-token/",
        data=b"{}",
        content_type="application/json",
    )

    assert response.status_code == 404


def test_webhook_ingest_invalid_tenant_slug_is_not_found() -> None:
    client = Client()

    response = client.post(
        "/t/Tenant-Upper/webhooks/polar/endpoint-token/",
        data=b"{}",
        content_type="application/json",
    )

    assert response.status_code == 404


@override_settings(
    WEBHOOK_ALLOW_GLOBAL_ENDPOINT_TOKEN=True,
    WEBHOOK_ENDPOINT_TOKEN="global-token",
)
def test_webhook_ingest_rejects_unsupported_payment_provider_before_enqueue() -> None:
    client = Client()

    response = client.post(
        "/t/tenant-a/webhooks/notreal/global-token/",
        data=b"{}",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert WebhookInboundEvent.objects.count() == 0


def test_webhook_ingest_ignores_unsupported_paddle_event_before_enqueue(monkeypatch) -> None:
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.validate_endpoint_token",
        lambda tenant_slug, provider, endpoint_token: True,
    )
    client = Client()

    response = client.post(
        "/t/tenant-a/webhooks/paddle/endpoint-token/",
        data=json.dumps({"event_type": "payment_method.saved", "data": {}}).encode("utf-8"),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "event_type": "payment_method.saved"}
    assert WebhookInboundEvent.objects.count() == 0


def test_webhook_ingest_stores_supported_paddle_event(monkeypatch) -> None:
    seen: list[int] = []
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.validate_endpoint_token",
        lambda tenant_slug, provider, endpoint_token: True,
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.tasks.process_inbound_webhook_event.delay",
        lambda event_id, **kwargs: seen.append(event_id),
    )
    client = Client()

    response = client.post(
        "/t/tenant-a/webhooks/paddle/endpoint-token/",
        data=json.dumps({"event_type": "transaction.completed", "data": {}}).encode("utf-8"),
        content_type="application/json",
    )

    assert response.status_code == 202
    assert WebhookInboundEvent.objects.count() == 1
    assert seen


def test_webhook_ingest_returns_503_when_queue_publish_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.validate_endpoint_token",
        lambda tenant_slug, provider, endpoint_token: True,
    )

    def _raise_queue_error(event_id: int, **kwargs: object) -> None:
        del event_id, kwargs
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "payglue_backend.webhooks.tasks.process_inbound_webhook_event.delay",
        _raise_queue_error,
    )

    client = Client()
    response = client.post(
        "/t/tenant-a/webhooks/polar/endpoint-token/",
        data=b"{}",
        content_type="application/json",
    )

    assert response.status_code == 503
    event = WebhookInboundEvent.objects.get()
    assert event.status == WebhookInboundEvent.Status.FAILED


def test_webhook_ingest_rejects_oversized_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.validate_endpoint_token",
        lambda tenant_slug, provider, endpoint_token: True,
    )
    client = Client()

    response = client.post(
        "/t/tenant-a/webhooks/polar/endpoint-token/",
        data=b"x" * 70000,
        content_type="application/octet-stream",
    )

    assert response.status_code == 413

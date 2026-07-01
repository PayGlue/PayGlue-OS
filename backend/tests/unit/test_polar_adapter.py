import hashlib
import hmac
import json
import base64
from datetime import UTC, datetime

import pytest

from payglue_backend.core.errors import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    MissingCredentialsError,
)
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters.polar import PolarPaymentAdapter


class StubCredentialProvider:
    def __init__(self, secret: str = "test-secret") -> None:
        self._secret = secret

    def get_credentials(
        self, tenant_ctx: TenantContext, provider_key: str
    ) -> dict[str, str]:
        assert tenant_ctx.tenant_slug == "tenant-a"
        assert provider_key == "polar"
        return {"webhook_secret": self._secret}


class _HealthCredentialProvider:
    def __init__(self, credentials: dict[str, str]) -> None:
        self._credentials = credentials

    def get_credentials(
        self, tenant_ctx: TenantContext, provider_key: str
    ) -> dict[str, str]:
        assert tenant_ctx.tenant_slug == "tenant-a"
        assert provider_key == "polar"
        return dict(self._credentials)


class _StubHealthClient:
    def __init__(
        self,
        result: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict[str, object]] = []

    def check_health(
        self, credentials: dict[str, str], tenant_ctx: TenantContext
    ) -> dict[str, object]:
        self.calls.append(
            {"credentials": credentials, "tenant_slug": tenant_ctx.tenant_slug}
        )
        if self._error is not None:
            raise self._error
        return dict(self._result or {"ok": True, "code": "ok", "message": "ok"})


def _make_signature(secret: str, timestamp: int, body: bytes) -> str:
    signed_payload = str(timestamp).encode("utf-8") + b"." + body
    digest = hmac.new(
        secret.encode("utf-8"), signed_payload, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def _make_standard_signature(
    secret: str, event_id: str, timestamp: int, body: bytes
) -> str:
    message = f"{event_id}.{timestamp}.".encode("utf-8") + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return f"v1,{base64.b64encode(digest).decode('ascii')}"


def test_verify_webhook_accepts_valid_signature() -> None:
    body = b'{"id":"evt_1"}'
    timestamp = 1704067200
    adapter = PolarPaymentAdapter(
        credential_provider=StubCredentialProvider(),
        now=lambda: datetime.fromtimestamp(timestamp, tz=UTC),
    )
    headers = {"Polar-Signature": _make_signature("test-secret", timestamp, body)}

    adapter.verify_webhook(body, headers, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_rejects_invalid_signature() -> None:
    body = b'{"id":"evt_1"}'
    timestamp = 1704067200
    adapter = PolarPaymentAdapter(
        credential_provider=StubCredentialProvider(),
        now=lambda: datetime.fromtimestamp(timestamp, tz=UTC),
    )

    with pytest.raises(InvalidWebhookSignatureError):
        adapter.verify_webhook(
            body,
            {"Polar-Signature": f"t={timestamp},v1=bad"},
            TenantContext(tenant_slug="tenant-a"),
        )


def test_verify_webhook_rejects_stale_timestamp() -> None:
    body = b'{"id":"evt_1"}'
    timestamp = 1704067200
    adapter = PolarPaymentAdapter(
        credential_provider=StubCredentialProvider(),
        now=lambda: datetime.fromtimestamp(timestamp + 1000, tz=UTC),
        timestamp_tolerance_seconds=300,
    )
    headers = {"Polar-Signature": _make_signature("test-secret", timestamp, body)}

    with pytest.raises(InvalidWebhookSignatureError):
        adapter.verify_webhook(body, headers, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_accepts_standard_webhook_headers() -> None:
    body = b'{"id":"evt_1"}'
    event_id = "evt_std"
    timestamp = 1704067200
    adapter = PolarPaymentAdapter(
        credential_provider=StubCredentialProvider(),
        now=lambda: datetime.fromtimestamp(timestamp, tz=UTC),
    )
    headers = {
        "webhook-id": event_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": _make_standard_signature(
            "test-secret", event_id, timestamp, body
        ),
    }

    adapter.verify_webhook(body, headers, TenantContext(tenant_slug="tenant-a"))


def test_parse_event_normalizes_order_paid_payload() -> None:
    adapter = PolarPaymentAdapter(credential_provider=StubCredentialProvider())
    payload = {
        "id": "evt_123",
        "type": "order.paid",
        "timestamp": "2026-01-01T00:00:00Z",
        "data": {
            "status": "paid",
            "customer": {"id": "cus_001", "email": "owner@example.com"},
            "product": {"id": "prod_123"},
            "currency": "usd",
            "items": [{"amount": 1500}],
        },
    }

    event = adapter.parse_event(json.dumps(payload).encode("utf-8"), {})

    assert event.provider == "polar"
    assert event.provider_event_id == "evt_123"
    assert event.event_type == "order.paid"
    assert event.customer.external_id == "cus_001"
    assert event.customer.email == "owner@example.com"
    assert len(event.line_items) == 1
    assert event.line_items[0].external_product_id == "prod_123"
    assert event.line_items[0].quantity == 1
    assert event.line_items[0].amount_minor == 1500
    assert event.line_items[0].currency == "USD"
    assert event.status == "paid"


def test_parse_event_raises_on_unsupported_payload_shape() -> None:
    adapter = PolarPaymentAdapter(credential_provider=StubCredentialProvider())
    bad_payload = {"id": "evt_123", "type": "order.paid", "data": {}}

    with pytest.raises(InvalidWebhookPayloadError):
        adapter.parse_event(json.dumps(bad_payload).encode("utf-8"), {})


def test_health_check_reports_success() -> None:
    health_client = _StubHealthClient(
        result={"ok": True, "code": "ok", "message": "polar credentials look good"}
    )
    adapter = PolarPaymentAdapter(
        credential_provider=_HealthCredentialProvider(
            credentials={"webhook_secret": "test-secret"}
        ),
        health_client=health_client,
    )

    result = adapter.health_check(TenantContext(tenant_slug="tenant-a"))

    assert result == {
        "ok": True,
        "code": "ok",
        "message": "polar credentials look good",
    }
    assert len(health_client.calls) == 1


def test_health_check_raises_for_missing_required_credentials() -> None:
    adapter = PolarPaymentAdapter(
        credential_provider=_HealthCredentialProvider(credentials={}),
    )

    with pytest.raises(MissingCredentialsError):
        adapter.health_check(TenantContext(tenant_slug="tenant-a"))


def test_health_check_maps_client_failures() -> None:
    adapter = PolarPaymentAdapter(
        credential_provider=_HealthCredentialProvider(
            credentials={"webhook_secret": "test-secret"}
        ),
        health_client=_StubHealthClient(error=RuntimeError("service unavailable")),
    )

    result = adapter.health_check(TenantContext(tenant_slug="tenant-a"))

    assert result["ok"] is False
    assert result["code"] == "transport_error"
    assert "failed" in str(result["message"]).lower()

from datetime import UTC, datetime
import hashlib
import hmac
import json

import pytest

from payglue_backend.core.errors import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    MissingCredentialsError,
    UnsupportedEventTypeError,
)
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters.paddle import PaddlePaymentAdapter


class StubCredentialProvider:
    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {
            "api_key": "pdl_sdbx_apikey_test",
            "webhook_secret": "whsec_test",
        }

    def get_credentials(self, tenant_ctx: TenantContext, provider_key: str) -> dict[str, str]:
        assert tenant_ctx.tenant_slug == "tenant-a"
        assert provider_key == "paddle"
        return dict(self._credentials)


def _sign(body: bytes, secret: str, ts: int) -> str:
    signed_payload = f"{ts}:".encode() + body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"ts={ts};h1={digest}"


def test_verify_webhook_accepts_valid_signature() -> None:
    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)
    adapter = PaddlePaymentAdapter(
        credential_provider=StubCredentialProvider(), now=lambda: fixed_now
    )
    body = json.dumps({"event_type": "transaction.completed"}).encode("utf-8")
    ts = int(fixed_now.timestamp())
    headers = {"Paddle-Signature": _sign(body, "whsec_test", ts)}

    adapter.verify_webhook(body, headers, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_rejects_invalid_signature() -> None:
    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)
    adapter = PaddlePaymentAdapter(
        credential_provider=StubCredentialProvider(), now=lambda: fixed_now
    )
    body = json.dumps({"event_type": "transaction.completed"}).encode("utf-8")
    ts = int(fixed_now.timestamp())
    headers = {"Paddle-Signature": f"ts={ts};h1=deadbeef"}

    with pytest.raises(InvalidWebhookSignatureError):
        adapter.verify_webhook(body, headers, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_accepts_missing_signature_header() -> None:
    adapter = PaddlePaymentAdapter(credential_provider=StubCredentialProvider())
    adapter.verify_webhook(b"{}", {}, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_rejects_stale_timestamp() -> None:
    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)
    adapter = PaddlePaymentAdapter(
        credential_provider=StubCredentialProvider(), now=lambda: fixed_now
    )
    body = json.dumps({"event_type": "transaction.completed"}).encode("utf-8")
    stale_ts = int(fixed_now.timestamp()) - 3600
    headers = {"Paddle-Signature": _sign(body, "whsec_test", stale_ts)}

    with pytest.raises(InvalidWebhookSignatureError):
        adapter.verify_webhook(body, headers, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_raises_on_missing_credentials() -> None:
    adapter = PaddlePaymentAdapter(
        credential_provider=StubCredentialProvider({"api_key": "pdl_sdbx_apikey_test"})
    )
    with pytest.raises(MissingCredentialsError):
        adapter.verify_webhook(b"{}", {}, TenantContext(tenant_slug="tenant-a"))


def test_parse_event_transaction_completed_resolves_customer_email(monkeypatch) -> None:
    class _FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=10):
        assert "customers/ctm_001" in req.full_url
        return _FakeResponse(json.dumps({"data": {"email": "buyer@example.com"}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = PaddlePaymentAdapter(credential_provider=StubCredentialProvider())
    payload = {
        "event_id": "ntf_123",
        "event_type": "transaction.completed",
        "occurred_at": "2026-01-01T00:00:00Z",
        "data": {
            "id": "txn_123",
            "customer_id": "ctm_001",
            "currency_code": "USD",
            "items": [{"quantity": 2, "price": {"id": "pri_1", "product_id": "pro_1"}}],
            "details": {"totals": {"total": "1999", "currency_code": "USD"}},
        },
    }

    event = adapter.parse_event(
        json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
    )

    assert event.provider == "paddle"
    assert event.provider_event_id == "ntf_123"
    assert event.event_type == "order.paid"
    assert event.customer.email == "buyer@example.com"
    assert event.customer.external_id == "ctm_001"
    assert event.line_items[0].external_product_id == "pro_1"
    assert event.line_items[0].quantity == 2
    assert event.line_items[0].amount_minor == 1999
    assert event.line_items[0].currency == "USD"
    assert event.status == "paid"


def test_parse_event_subscription_canceled_uses_nested_customer_email() -> None:
    adapter = PaddlePaymentAdapter(credential_provider=StubCredentialProvider())
    payload = {
        "event_id": "ntf_456",
        "event_type": "subscription.canceled",
        "data": {
            "id": "sub_123",
            "customer_id": "ctm_002",
            "status": "canceled",
            "currency_code": "USD",
            "customer": {"email": "member@example.com"},
            "items": [{"price": {"id": "pri_2", "product_id": "pro_2"}}],
        },
    }

    event = adapter.parse_event(
        json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
    )

    assert event.event_type == "subscription.canceled"
    assert event.customer.email == "member@example.com"
    assert event.line_items[0].external_product_id == "pro_2"


def test_parse_event_raises_on_unsupported_event_type() -> None:
    adapter = PaddlePaymentAdapter(credential_provider=StubCredentialProvider())
    payload = {"event_id": "ntf_1", "event_type": "product.created", "data": {"id": "pro_1"}}

    with pytest.raises(UnsupportedEventTypeError):
        adapter.parse_event(
            json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
        )


def test_parse_event_raises_on_invalid_json() -> None:
    adapter = PaddlePaymentAdapter(credential_provider=StubCredentialProvider())
    with pytest.raises(InvalidWebhookPayloadError):
        adapter.parse_event(b"not json", {}, TenantContext(tenant_slug="tenant-a"))


def test_health_check_reports_success(monkeypatch) -> None:
    class _FakeResponse:
        def read(self) -> bytes:
            return b'{"data": []}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=10: _FakeResponse())

    adapter = PaddlePaymentAdapter(credential_provider=StubCredentialProvider())
    result = adapter.health_check(TenantContext(tenant_slug="tenant-a"))

    assert result["ok"] is True


def test_health_check_raises_for_missing_api_key() -> None:
    adapter = PaddlePaymentAdapter(
        credential_provider=StubCredentialProvider({"webhook_secret": "whsec_test"})
    )
    with pytest.raises(MissingCredentialsError):
        adapter.health_check(TenantContext(tenant_slug="tenant-a"))

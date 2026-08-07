from datetime import UTC, datetime
import hashlib
import hmac
import json
import urllib.error

import pytest

from payglue_backend.core.errors import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    MissingCredentialsError,
    UnsupportedEventTypeError,
)
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters.creem import CreemPaymentAdapter


class StubCredentialProvider:
    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials or {
            "api_key": "creem_test_apikey",
            "webhook_secret": "whsec_test",
        }

    def get_credentials(self, tenant_ctx: TenantContext, provider_key: str) -> dict[str, str]:
        assert tenant_ctx.tenant_slug == "tenant-a"
        assert provider_key == "creem"
        return dict(self._credentials)


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_verify_webhook_accepts_valid_signature() -> None:
    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    body = json.dumps({"eventType": "checkout.completed"}).encode("utf-8")
    headers = {"creem-signature": _sign(body, "whsec_test")}

    adapter.verify_webhook(body, headers, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_rejects_invalid_signature() -> None:
    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    body = json.dumps({"eventType": "checkout.completed"}).encode("utf-8")
    headers = {"creem-signature": "deadbeef"}

    with pytest.raises(InvalidWebhookSignatureError):
        adapter.verify_webhook(body, headers, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_rejects_missing_signature() -> None:
    # Unlike Gumroad/Paddle, Creem reliably signs every delivery -- a missing
    # header must be rejected, not treated as optional.
    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    with pytest.raises(InvalidWebhookSignatureError):
        adapter.verify_webhook(b"{}", {}, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_raises_on_missing_credentials() -> None:
    adapter = CreemPaymentAdapter(
        credential_provider=StubCredentialProvider({"api_key": "creem_test_apikey"})
    )
    with pytest.raises(MissingCredentialsError):
        adapter.verify_webhook(b"{}", {}, TenantContext(tenant_slug="tenant-a"))


def test_parse_event_checkout_completed_with_inline_customer() -> None:
    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    payload = {
        "id": "evt_123",
        "eventType": "checkout.completed",
        "object": {
            "id": "ch_123",
            "customer": {"id": "cust_001", "email": "buyer@example.com"},
            "product": {"id": "prod_1"},
            "amount": 1999,
            "currency": "usd",
        },
    }

    event = adapter.parse_event(
        json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
    )

    assert event.provider == "creem"
    assert event.provider_event_id == "evt_123"
    assert event.event_type == "order.paid"
    assert event.customer.email == "buyer@example.com"
    assert event.customer.external_id == "cust_001"
    assert event.line_items[0].external_product_id == "prod_1"
    assert event.line_items[0].amount_minor == 1999
    assert event.line_items[0].currency == "USD"
    assert event.status == "paid"


def test_parse_event_checkout_completed_resolves_customer_email_via_api(monkeypatch) -> None:
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
        assert "customers?customer_id=cust_002" in req.full_url
        return _FakeResponse(json.dumps({"email": "member@example.com"}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    payload = {
        "id": "evt_456",
        "eventType": "checkout.completed",
        "object": {
            "id": "ch_456",
            "customer": "cust_002",
            "product": "prod_2",
            "amount": 500,
            "currency": "EUR",
        },
    }

    event = adapter.parse_event(
        json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
    )

    assert event.customer.email == "member@example.com"
    assert event.customer.external_id == "cust_002"
    assert event.line_items[0].external_product_id == "prod_2"
    assert event.line_items[0].currency == "EUR"


def test_parse_event_subscription_active() -> None:
    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    payload = {
        "id": "evt_789",
        "eventType": "subscription.active",
        "object": {
            "id": "sub_1",
            "customer": {"id": "cust_003", "email": "sub@example.com"},
            "product": {"id": "prod_3"},
            "status": "active",
        },
    }

    event = adapter.parse_event(
        json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
    )

    assert event.event_type == "subscription.active"
    assert event.customer.email == "sub@example.com"
    assert event.status == "active"


def test_parse_event_raises_on_unsupported_event_type() -> None:
    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    payload = {"id": "evt_1", "eventType": "refund.created", "object": {"id": "ref_1"}}

    with pytest.raises(UnsupportedEventTypeError):
        adapter.parse_event(
            json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
        )


def test_parse_event_raises_on_invalid_json() -> None:
    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    with pytest.raises(InvalidWebhookPayloadError):
        adapter.parse_event(b"not json", {}, TenantContext(tenant_slug="tenant-a"))


def test_health_check_reports_success(monkeypatch) -> None:
    class _FakeResponse:
        def read(self) -> bytes:
            return b"[]"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=10: _FakeResponse())

    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    result = adapter.health_check(TenantContext(tenant_slug="tenant-a"))

    assert result["ok"] is True


def test_health_check_falls_back_from_sandbox_to_live_mode(monkeypatch) -> None:
    # A Creem API key belongs to exactly one mode (test vs. live) -- there is
    # no way to tell which from the key string alone, so the adapter must
    # try sandbox first and fall back to live automatically rather than
    # requiring the tenant to declare it via a toggle.
    class _FakeResponse:
        def read(self) -> bytes:
            return b'{"items": []}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    calls: list[str] = []

    def fake_urlopen(req, timeout=10):
        calls.append(req.full_url)
        if "test-api.creem.io" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    result = adapter.health_check(TenantContext(tenant_slug="tenant-a"))

    assert result["ok"] is True
    assert calls == [
        "https://test-api.creem.io/v1/products/search",
        "https://api.creem.io/v1/products/search",
    ]


def test_health_check_surfaces_creem_error_body(monkeypatch) -> None:
    import io

    def fake_urlopen(req, timeout=10):
        raise urllib.error.HTTPError(
            req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"message": "Invalid API key"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    result = adapter.health_check(TenantContext(tenant_slug="tenant-a"))

    assert result["ok"] is False
    assert "Invalid API key" in result["message"]


def test_health_check_raises_for_missing_api_key() -> None:
    adapter = CreemPaymentAdapter(
        credential_provider=StubCredentialProvider({"webhook_secret": "whsec_test"})
    )
    with pytest.raises(MissingCredentialsError):
        adapter.health_check(TenantContext(tenant_slug="tenant-a"))


def test_supports_event() -> None:
    adapter = CreemPaymentAdapter(credential_provider=StubCredentialProvider())
    assert adapter.supports_event("order.paid") is True
    assert adapter.supports_event("subscription.active") is True
    assert adapter.supports_event("unknown") is False

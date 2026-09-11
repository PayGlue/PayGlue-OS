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
    UnsupportedEventTypeError,
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


def _standard_headers(key: bytes, event_id: str, timestamp: int, body: bytes) -> dict[str, str]:
    message = f"{event_id}.{timestamp}.".encode("utf-8") + body
    digest = hmac.new(key, message, hashlib.sha256).digest()
    return {
        "webhook-id": event_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": f"v1,{base64.b64encode(digest).decode('ascii')}",
    }


def test_standard_webhook_accepts_secret_generated_after_september_2026() -> None:
    """Standard Webhooks key: the base64-decoded part after whsec_."""
    body = b'{"id":"evt_1"}'
    timestamp = 1704067200
    key = b"\x01\x02new-style-key-bytes\xff"
    secret = "whsec_" + base64.b64encode(key).decode("ascii")
    adapter = PolarPaymentAdapter(
        credential_provider=StubCredentialProvider(secret),
        now=lambda: datetime.fromtimestamp(timestamp, tz=UTC),
    )

    adapter.verify_webhook(
        body, _standard_headers(key, "evt_new", timestamp, body), TenantContext(tenant_slug="tenant-a")
    )


def test_standard_webhook_accepts_older_polar_secret_that_looks_like_base64() -> None:
    """Older Polar secrets sign with the UTF-8 bytes of the whole string. One
    that happens to decode as base64 must still verify."""
    body = b'{"id":"evt_1"}'
    timestamp = 1704067200
    secret = "whsec_abcdefghijklmnop"  # valid base64, but the key is the raw string
    adapter = PolarPaymentAdapter(
        credential_provider=StubCredentialProvider(secret),
        now=lambda: datetime.fromtimestamp(timestamp, tz=UTC),
    )

    adapter.verify_webhook(
        body,
        _standard_headers(secret.encode("utf-8"), "evt_old", timestamp, body),
        TenantContext(tenant_slug="tenant-a"),
    )


def test_standard_webhook_rejects_wrong_key_under_both_schemes() -> None:
    body = b'{"id":"evt_1"}'
    timestamp = 1704067200
    adapter = PolarPaymentAdapter(
        credential_provider=StubCredentialProvider("whsec_abcdefghijklmnop"),
        now=lambda: datetime.fromtimestamp(timestamp, tz=UTC),
    )

    with pytest.raises(InvalidWebhookSignatureError):
        adapter.verify_webhook(
            body, _standard_headers(b"somebody-else", "evt_x", timestamp, body), TenantContext(tenant_slug="tenant-a")
        )


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

    event = adapter.parse_event(
        json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
    )

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
        adapter.parse_event(
            json.dumps(bad_payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
        )


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


def test_parse_event_takes_the_product_id_from_the_item_when_the_order_has_none() -> None:
    """Polar puts the canonical product at data.product, but not in every shape."""
    adapter = PolarPaymentAdapter(credential_provider=StubCredentialProvider())
    payload = {
        "id": "evt_124",
        "type": "order.paid",
        "timestamp": "2026-01-01T00:00:00Z",
        "data": {
            "status": "paid",
            "customer": {"id": "cus_001", "email": "owner@example.com"},
            "currency": "usd",
            "items": [{"amount": 1500, "product_id": "prod_from_item"}],
        },
    }

    event = adapter.parse_event(
        json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
    )

    assert event.line_items[0].external_product_id == "prod_from_item"


def test_parse_event_refuses_to_invent_a_product_id_from_the_order_item(caplog) -> None:
    """PG-231: this used to fall back to the order item's own id.

    That id is unique per purchase, so it could never match a mapping. The
    event was recorded as processed, nothing was granted, and no error was
    raised anywhere. Failing is the better outcome: a failed event is visible
    in the log and can be replayed once the payload shape is understood.
    """
    adapter = PolarPaymentAdapter(credential_provider=StubCredentialProvider())
    payload = {
        "id": "evt_125",
        "type": "order.paid",
        "timestamp": "2026-01-01T00:00:00Z",
        "data": {
            "status": "paid",
            "customer": {"id": "cus_001", "email": "owner@example.com"},
            "currency": "usd",
            # No data.product, and the item carries only its own id.
            "items": [{"id": "66de50aa-ca54-4f40-bdcf-718969ed4995", "amount": 1500}],
        },
    }

    with pytest.raises(InvalidWebhookPayloadError):
        adapter.parse_event(
            json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
        )


# --- PG-257: Polar's subscription payloads -----------------------------------
#
# Every one of these failed in production until 14.08.2026. `subscription.active`
# and `subscription.revoked` went to the order parser, which asks for a
# `data.items` array a subscription payload does not carry, and the cancel
# parser only accepted the nested `data.subscription` shape that a real Polar
# cancellation does not use. The grant side was covered by the separate
# `order.paid` event, so nobody noticed. The cancel side was not: not one Polar
# cancellation had ever been processed.
#
# The payloads below are the shapes taken off real events in production.


def _subscription_payload(event_type: str, **overrides) -> dict:
    """A Polar subscription payload, flat, as it actually arrives."""
    data = {
        "id": "sub_001",
        "status": "active",
        "customer": {"id": "cus_001", "email": "reader@example.com"},
        "product": {"id": "prod_123"},
        "amount": 500,
        "currency": "usd",
        "cancel_at_period_end": False,
        "canceled_at": None,
        "current_period_end": "2026-09-14T07:49:57Z",
    }
    data.update(overrides)
    return {
        "id": f"evt_{event_type}",
        "type": event_type,
        "timestamp": "2026-08-14T08:00:00Z",
        "data": data,
    }


def _parse(payload: dict):
    return PolarPaymentAdapter(credential_provider=StubCredentialProvider()).parse_event(
        json.dumps(payload).encode("utf-8"), {}, TenantContext(tenant_slug="tenant-a")
    )


@pytest.mark.parametrize("event_type", ["subscription.active", "subscription.revoked"])
def test_a_flat_subscription_payload_parses(event_type: str) -> None:
    """The product sits in data.product, not in a data.items array."""
    event = _parse(_subscription_payload(event_type))

    assert event.event_type == event_type
    assert event.customer.email == "reader@example.com"
    assert [i.external_product_id for i in event.line_items] == ["prod_123"]


def test_a_cancellation_booked_for_the_period_end_is_skipped() -> None:
    """The member paid through current_period_end and keeps access until then.
    Polar sends subscription.revoked once the period is actually over, and that
    is the event that withdraws access. Skipped, not failed: doing nothing is
    the right outcome here, so there is nothing to retry."""
    with pytest.raises(UnsupportedEventTypeError):
        _parse(
            _subscription_payload(
                "subscription.canceled",
                cancel_at_period_end=True,
                canceled_at="2026-08-14T08:08:17Z",
                current_period_end="2099-01-01T00:00:00Z",
            )
        )


def test_a_cancellation_whose_period_already_ran_out_is_an_ending() -> None:
    event = _parse(
        _subscription_payload(
            "subscription.canceled",
            cancel_at_period_end=True,
            current_period_end="2020-01-01T00:00:00Z",
        )
    )

    assert event.event_type == "subscription.canceled"


def test_an_immediate_cancellation_is_an_ending() -> None:
    """Without cancel_at_period_end there is no paid time left to honour."""
    event = _parse(_subscription_payload("subscription.canceled"))

    assert event.event_type == "subscription.canceled"


def test_an_unreadable_period_end_keeps_the_access() -> None:
    """Keeping access one cycle too long is a smaller wrong than taking it
    from somebody who paid for it."""
    with pytest.raises(UnsupportedEventTypeError):
        _parse(
            _subscription_payload(
                "subscription.canceled",
                cancel_at_period_end=True,
                current_period_end="not a date",
            )
        )


def test_the_nested_shape_still_parses() -> None:
    """Some payloads wrap the subscription. Both shapes stay supported."""
    payload = {
        "id": "evt_nested",
        "type": "subscription.canceled",
        "timestamp": "2026-08-14T08:00:00Z",
        "data": {
            "subscription": {
                "status": "canceled",
                "customer": {"id": "cus_002", "email": "other@example.com"},
                "product": {"id": "prod_999"},
                "cancel_at_period_end": False,
            }
        },
    }

    event = _parse(payload)

    assert event.customer.email == "other@example.com"
    assert [i.external_product_id for i in event.line_items] == ["prod_999"]

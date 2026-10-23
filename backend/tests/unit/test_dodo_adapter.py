# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Dodo Payments adapter.

The payloads follow the field names of Dodo's official SDK types (`Payment`,
`Subscription`) and its webhook envelope (`business_id`, `type`, `timestamp`,
`data`). They are documentation-shaped, not captured deliveries. Real
test-mode payloads replace them as fixtures once a purchase, renewal,
cancellation and expiry have gone through.
"""
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest import mock

import pytest

from payglue_backend.core.errors import InvalidWebhookSignatureError, UnsupportedEventTypeError
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters import dodo
from payglue_backend.webhooks.adapters.dodo import DodoPaymentAdapter

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
KEY = b"dodo-test-signing-key-32-bytes!!"
SECRET = "whsec_" + base64.b64encode(KEY).decode("ascii")
CTX = TenantContext(tenant_slug="tenant-a")


class _Credentials:
    def get_credentials(self, tenant_ctx, provider_key):
        return {"webhook_secret": SECRET, "api_key": "dodo_test_key"}


def _adapter() -> DodoPaymentAdapter:
    return DodoPaymentAdapter(credential_provider=_Credentials(), now=lambda: NOW)


def _headers(body: bytes, msg_id: str = "msg_1", ts: int | None = None, key: bytes = KEY) -> dict[str, str]:
    ts = ts if ts is not None else int(NOW.timestamp())
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"webhook-id": msg_id, "webhook-timestamp": str(ts), "webhook-signature": f"v1,{sig}"}


CUSTOMER = {"customer_id": "cus_1", "email": "Reader@Example.com", "name": "Reader"}


def _payment(subscription_ids=()) -> bytes:
    return json.dumps(
        {
            "business_id": "bus_1",
            "type": "payment.succeeded",
            "timestamp": "2026-10-23T11:59:00Z",
            "data": {
                "payment_id": "pay_1",
                "customer": CUSTOMER,
                "currency": "EUR",
                "total_amount": 900,
                "subscription_ids": list(subscription_ids),
                "product_cart": [{"product_id": "pdt_archive", "quantity": 1}],
            },
        }
    ).encode()


def _subscription(event: str, **fields) -> bytes:
    data = {
        "subscription_id": "sub_1",
        "product_id": "pdt_member",
        "customer": CUSTOMER,
        "currency": "EUR",
        "recurring_pre_tax_amount": 500,
        "status": "active",
        "cancel_at_next_billing_date": False,
        "next_billing_date": "2026-11-23T00:00:00Z",
    }
    data.update(fields)
    return json.dumps({"business_id": "bus_1", "type": event, "timestamp": "2026-10-23T11:59:00Z", "data": data}).encode()


@pytest.fixture(autouse=True)
def _test_key():
    with mock.patch.object(dodo, "dodo_key_mode", return_value="test"):
        yield


def test_a_valid_standard_webhooks_signature_passes() -> None:
    body = _payment()
    _adapter().verify_webhook(body, _headers(body), CTX)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda b, h: (b + b" ", h),
        lambda b, h: (b, {**h, "webhook-id": "msg_other"}),
        lambda b, h: (b, _headers(b, key=b"another-key-entirely-32-bytes!!!")),
        lambda b, h: (b, _headers(b, ts=int(NOW.timestamp()) - 3600)),
    ],
    ids=["body changed", "id changed", "wrong secret", "stale timestamp"],
)
def test_anything_that_does_not_match_is_rejected(tamper) -> None:
    body = _payment()
    body, headers = tamper(body, _headers(body))
    with pytest.raises(InvalidWebhookSignatureError):
        _adapter().verify_webhook(body, headers, CTX)


def test_a_missing_header_names_itself() -> None:
    body = _payment()
    headers = _headers(body)
    del headers["webhook-signature"]
    with pytest.raises(InvalidWebhookSignatureError, match="webhook-signature"):
        _adapter().verify_webhook(body, headers, CTX)


def test_a_one_time_payment_grants_access_and_uses_the_webhook_id() -> None:
    body = _payment()
    event = _adapter().parse_event(body, _headers(body, msg_id="msg_42"), CTX)
    assert event.event_type == "order.paid"
    assert event.provider_event_id == "msg_42"
    assert event.customer.email == "reader@example.com"
    assert event.line_items[0].external_product_id == "pdt_archive"
    assert event.line_items[0].amount_minor == 900
    assert event.is_test


def test_a_subscription_payment_is_left_to_the_subscription_events() -> None:
    body = _payment(subscription_ids=["sub_1"])
    with pytest.raises(UnsupportedEventTypeError):
        _adapter().parse_event(body, _headers(body), CTX)


@pytest.mark.parametrize("event", ["subscription.active", "subscription.renewed"])
def test_activation_and_renewal_grant_access(event: str) -> None:
    body = _subscription(event)
    parsed = _adapter().parse_event(body, _headers(body), CTX)
    assert parsed.event_type == "subscription.active"
    assert parsed.line_items[0].external_product_id == "pdt_member"


def test_a_cancellation_at_period_end_keeps_access_until_then() -> None:
    body = _subscription("subscription.cancelled", cancel_at_next_billing_date=True)
    with pytest.raises(UnsupportedEventTypeError, match="2026-11-23"):
        _adapter().parse_event(body, _headers(body), CTX)


def test_an_immediate_cancellation_ends_access() -> None:
    body = _subscription("subscription.cancelled", status="cancelled")
    assert _adapter().parse_event(body, _headers(body), CTX).event_type == "subscription.revoked"


def test_the_expiry_ends_access() -> None:
    body = _subscription("subscription.expired", status="expired")
    assert _adapter().parse_event(body, _headers(body), CTX).event_type == "subscription.revoked"


@pytest.mark.parametrize("event", ["subscription.on_hold", "subscription.past_due", "subscription.paused", "refund.succeeded"])
def test_events_without_an_access_change_are_skipped(event: str) -> None:
    body = _subscription(event)
    with pytest.raises(UnsupportedEventTypeError):
        _adapter().parse_event(body, _headers(body), CTX)


def test_a_live_key_does_not_mark_events_as_test() -> None:
    body = _payment()
    with mock.patch.object(dodo, "dodo_key_mode", return_value="live"):
        assert not _adapter().parse_event(body, _headers(body), CTX).is_test


# -- Real test-mode payloads --------------------------------------------------
# Captured on staging on 2026-10-23 from a Dodo Payments test-mode purchase of
# a monthly subscription. Customer, billing address and card details are
# replaced; everything else is as Dodo sent it. Dodo sends subscription.active
# and subscription.renewed together when a subscription starts, plus the
# payment, which carries the subscription id.

from pathlib import Path  # noqa: E402

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "dodo"


def _real(name: str) -> bytes:
    return (_FIXTURES / f"{name}.json").read_bytes()


@pytest.mark.parametrize("name", ["subscription_active", "subscription_renewed_first"])
def test_real_subscription_start_grants_access(name: str) -> None:
    body = _real(name)
    event = _adapter().parse_event(body, _headers(body, msg_id=f"msg_{name}"), CTX)
    assert event.event_type == "subscription.active"
    assert event.line_items[0].external_product_id == "pdt_0NqM81d8idbmOZNPNnJqC"
    assert event.customer.email == "reader@example.com"
    assert event.is_test


def test_real_subscription_payment_is_skipped() -> None:
    body = _real("payment_succeeded_subscription")
    with pytest.raises(UnsupportedEventTypeError, match="subscription"):
        _adapter().parse_event(body, _headers(body), CTX)


def test_real_payloads_verify_with_standard_webhooks() -> None:
    for name in ("subscription_active", "subscription_renewed_first", "payment_succeeded_subscription"):
        body = _real(name)
        _adapter().verify_webhook(body, _headers(body), CTX)


def test_real_immediate_cancellation_ends_access() -> None:
    # Cancelled from the Dodo dashboard with "cancel now": the flag is false
    # although next_billing_date still lies in the future.
    body = _real("subscription_cancelled_immediately")
    event = _adapter().parse_event(body, _headers(body), CTX)
    assert event.event_type == "subscription.revoked"
    assert event.line_items[0].external_product_id == "pdt_0NqM81d8idbmOZNPNnJqC"
    assert event.customer.email == "reader@example.com"


def test_real_one_time_payment_grants_access() -> None:
    # A one-time product: no subscription_id and no subscription_ids key at all.
    body = _real("payment_succeeded_one_time")
    event = _adapter().parse_event(body, _headers(body), CTX)
    assert event.event_type == "order.paid"
    assert event.line_items[0].external_product_id == "pdt_0NqM882QqFo8KUelC1y7u"
    assert event.line_items[0].amount_minor == 531
    assert event.customer.email == "reader@example.com"
    assert event.is_test

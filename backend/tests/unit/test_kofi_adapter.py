from datetime import UTC, datetime
from urllib.parse import urlencode
import json

import pytest

from payglue_backend.core.errors import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    MissingCredentialsError,
    UnsupportedEventTypeError,
)
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters.kofi import KofiPaymentAdapter


class StubCredentialProvider:
    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        self._credentials = (
            credentials if credentials is not None else {"verification_token": "tok_test"}
        )

    def get_credentials(self, tenant_ctx: TenantContext, provider_key: str) -> dict[str, str]:
        assert tenant_ctx.tenant_slug == "tenant-a"
        assert provider_key == "kofi"
        return dict(self._credentials)


def _body(data: dict) -> bytes:
    return urlencode({"data": json.dumps(data)}).encode("utf-8")


def test_verify_webhook_accepts_matching_verification_token() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())
    body = _body({"verification_token": "tok_test", "type": "Tip"})

    adapter.verify_webhook(body, {}, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_rejects_mismatched_verification_token() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())
    body = _body({"verification_token": "wrong-token", "type": "Tip"})

    with pytest.raises(InvalidWebhookSignatureError):
        adapter.verify_webhook(body, {}, TenantContext(tenant_slug="tenant-a"))


def test_verify_webhook_raises_on_missing_credentials() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider(credentials={}))
    body = _body({"verification_token": "tok_test", "type": "Tip"})

    with pytest.raises(MissingCredentialsError):
        adapter.verify_webhook(body, {}, TenantContext(tenant_slug="tenant-a"))


def test_parse_event_maps_donation_to_order_paid() -> None:
    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider(), now=lambda: fixed_now)
    body = _body(
        {
            "verification_token": "tok_test",
            "type": "Tip",
            "message_id": "msg_1",
            "kofi_transaction_id": "kofi_txn_1",
            "email": "supporter@example.com",
            "from_name": "A Supporter",
            "amount": "5.00",
            "currency": "USD",
            "timestamp": "2026-01-01T12:00:00Z",
        }
    )

    event = adapter.parse_event(body, {}, TenantContext(tenant_slug="tenant-a"))

    assert event.event_type == "order.paid"
    assert event.provider == "kofi"
    assert event.provider_event_id == "kofi_txn_1"
    assert event.customer.email == "supporter@example.com"
    assert event.line_items[0].amount_minor == 500
    assert event.line_items[0].currency == "USD"
    assert event.line_items[0].external_product_id == "kofi-support"
    assert event.status == "paid"


def test_parse_event_accepts_donation_type() -> None:
    # Ko-fi's own dashboard "Send Test" button still sends "Donation", the
    # legacy name their docs have since replaced with "Tip" -- both must work.
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())
    body = _body(
        {
            "verification_token": "tok_test",
            "type": "Donation",
            "message_id": "msg_5",
            "kofi_transaction_id": "kofi_txn_5",
            "email": "supporter@example.com",
            "amount": "3.00",
            "currency": "USD",
        }
    )

    event = adapter.parse_event(body, {}, TenantContext(tenant_slug="tenant-a"))

    assert event.event_type == "order.paid"


def test_parse_event_shop_order_uses_direct_link_code_per_item() -> None:
    # Ko-fi's real Shop Order payload has no product name at all -- only
    # shop_items[].direct_link_code identifies what was bought.
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())
    body = _body(
        {
            "verification_token": "tok_test",
            "type": "Shop Order",
            "message_id": "msg_6",
            "kofi_transaction_id": "kofi_txn_6",
            "email": "buyer@example.com",
            "amount": "27.95",
            "currency": "EUR",
            "tier_name": None,
            "shop_items": [
                {"direct_link_code": "1a2b3c4d5e"},
                {"direct_link_code": "a1b2c3d4e5"},
            ],
        }
    )

    event = adapter.parse_event(body, {}, TenantContext(tenant_slug="tenant-a"))

    product_ids = {li.external_product_id for li in event.line_items}
    assert product_ids == {"1a2b3c4d5e", "a1b2c3d4e5"}
    assert all(li.quantity == 1 for li in event.line_items)


def test_parse_event_shop_order_aggregates_duplicate_direct_link_codes() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())
    body = _body(
        {
            "verification_token": "tok_test",
            "type": "Shop Order",
            "message_id": "msg_7",
            "email": "buyer@example.com",
            "amount": "10.00",
            "shop_items": [
                {"direct_link_code": "1a2b3c4d5e"},
                {"direct_link_code": "1a2b3c4d5e"},
            ],
        }
    )

    event = adapter.parse_event(body, {}, TenantContext(tenant_slug="tenant-a"))

    assert len(event.line_items) == 1
    assert event.line_items[0].external_product_id == "1a2b3c4d5e"
    assert event.line_items[0].quantity == 2


def test_parse_event_shop_order_falls_back_to_bucket_without_shop_items() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())
    body = _body(
        {
            "verification_token": "tok_test",
            "type": "Shop Order",
            "message_id": "msg_8",
            "email": "buyer@example.com",
            "amount": "10.00",
        }
    )

    event = adapter.parse_event(body, {}, TenantContext(tenant_slug="tenant-a"))

    assert len(event.line_items) == 1
    assert event.line_items[0].external_product_id == "kofi-support"


def test_parse_event_uses_tier_name_as_product_id_for_subscriptions() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())
    body = _body(
        {
            "verification_token": "tok_test",
            "type": "Subscription",
            "message_id": "msg_2",
            "email": "member@example.com",
            "amount": "3.00",
            "currency": "USD",
            "tier_name": "Gold Tier",
            "is_first_subscription_payment": "true",
        }
    )

    event = adapter.parse_event(body, {}, TenantContext(tenant_slug="tenant-a"))

    assert event.line_items[0].external_product_id == "Gold Tier"


def test_parse_event_raises_on_missing_email() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())
    body = _body({"verification_token": "tok_test", "type": "Tip", "message_id": "msg_3"})

    with pytest.raises(InvalidWebhookPayloadError):
        adapter.parse_event(body, {}, TenantContext(tenant_slug="tenant-a"))


def test_parse_event_raises_on_unsupported_type() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())
    body = _body(
        {
            "verification_token": "tok_test",
            "type": "SomethingElse",
            "message_id": "msg_4",
            "email": "supporter@example.com",
        }
    )

    with pytest.raises(UnsupportedEventTypeError):
        adapter.parse_event(body, {}, TenantContext(tenant_slug="tenant-a"))


def test_supports_event_only_accepts_order_paid() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())

    assert adapter.supports_event("order.paid") is True
    assert adapter.supports_event("subscription.canceled") is False


def test_supports_raw_event_type() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())

    assert adapter.supports_raw_event_type("Tip") is True
    assert adapter.supports_raw_event_type("Donation") is True
    assert adapter.supports_raw_event_type("Shop Order") is True
    assert adapter.supports_raw_event_type("Unknown") is False


def test_health_check_raises_when_token_missing() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider(credentials={}))

    with pytest.raises(MissingCredentialsError):
        adapter.health_check(TenantContext(tenant_slug="tenant-a"))


def test_health_check_ok_when_token_present() -> None:
    adapter = KofiPaymentAdapter(credential_provider=StubCredentialProvider())

    result = adapter.health_check(TenantContext(tenant_slug="tenant-a"))

    assert result["ok"] is True

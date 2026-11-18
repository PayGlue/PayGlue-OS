# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Digistore24 adapter.

The signature test uses the worked example from Digistore24's IPN
documentation. The payloads follow the field names of the IPN event
reference; they are documentation-shaped, not captured deliveries. Real
test-purchase IPNs replace them as fixtures once a purchase, renewal,
cancellation and refund have gone through.
"""
import pathlib
from datetime import UTC, datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest

from payglue_backend.core.errors import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    MissingCredentialsError,
    UnsupportedEventTypeError,
)
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters import digistore24
from payglue_backend.webhooks.adapters.digistore24 import (
    Digistore24PaymentAdapter,
    clean_api_key,
    ds24_signature,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
PASSPHRASE = "ipn-test-passphrase"
CTX = TenantContext(tenant_slug="tenant-a")


class _Credentials:
    def __init__(self, creds=None):
        self._creds = {"webhook_secret": PASSPHRASE, "api_key": "123-abc"} if creds is None else creds

    def get_credentials(self, tenant_ctx, provider_key):
        return self._creds


def _adapter(creds=None) -> Digistore24PaymentAdapter:
    return Digistore24PaymentAdapter(credential_provider=_Credentials(creds), now=lambda: NOW)


def _body(fields: dict[str, str], passphrase: str = PASSPHRASE, *, sign: bool = True) -> bytes:
    pairs = list(fields.items())
    if sign:
        pairs.append(("sha_sign", ds24_signature(pairs, passphrase)))
    return urlencode(pairs).encode("utf-8")


def _payment(**overrides: str) -> dict[str, str]:
    fields = {
        "api_mode": "live",
        "event": "on_payment",
        "order_id": "ABC123XY",
        "transaction_id": "88001",
        "pay_sequence_no": "1",
        "product_id": "768495",
        "product_name": "Inner Circle",
        "email": "Reader@Example.com",
        "buyer_id": "4711",
        "address_first_name": "Rea",
        "address_last_name": "Der",
        "billing_type": "subscription",
        "billing_status": "paying",
        "transaction_amount": "9.00",
        "transaction_currency": "EUR",
        "next_payment_at": "2026-12-18",
        "custom": "",
    }
    fields.update(overrides)
    return fields


# --- signature ------------------------------------------------------------


def test_signature_matches_the_worked_example_in_the_documentation() -> None:
    fields = [
        ("buyer_email", "claus@domain-xyz.de"),
        ("order_id", "273732"),
        ("payment_id", "PAYID-39-22012"),
        ("transaction_amount", "17.00"),
        ("transaction_currency", "USD"),
    ]
    assert ds24_signature(fields, "xxxxx") == (
        "342770076245D14ED7DF4D2E5D82216D7EDF8F9E7969B5964C9C5DCB53E962BB"
        "ECD545E90422B5329C69554FD8B1A7E7410736615FCA7FB5CBB3624CC016E4BC"
    )


def test_signature_skips_empty_values_and_the_signature_field_itself() -> None:
    base = [("order_id", "1"), ("email", "a@b.c")]
    assert ds24_signature(base + [("custom", ""), ("sha_sign", "X")], "p") == ds24_signature(base, "p")


def test_verify_accepts_a_correct_signature() -> None:
    _adapter().verify_webhook(_body(_payment()), {}, CTX)


def test_verify_rejects_the_case_insensitive_order_the_documentation_describes() -> None:
    # A real delivery matched only the byte-wise order. `order_id` and
    # `orderform_id` sort differently byte-wise and upper-cased.
    fields = _payment(orderform_id="12")
    pairs = list(fields.items())
    pairs.append(("sha_sign", ds24_signature(pairs, PASSPHRASE, case_sensitive=False)))
    assert ds24_signature(pairs, PASSPHRASE) != ds24_signature(pairs, PASSPHRASE, case_sensitive=False)
    with pytest.raises(InvalidWebhookSignatureError):
        _adapter().verify_webhook(urlencode(pairs).encode(), {}, CTX)


def test_verify_accepts_a_lower_case_signature() -> None:
    pairs = list(_payment().items())
    pairs.append(("sha_sign", ds24_signature(pairs, PASSPHRASE).lower()))
    _adapter().verify_webhook(urlencode(pairs).encode(), {}, CTX)


def test_verify_rejects_a_wrong_passphrase() -> None:
    with pytest.raises(InvalidWebhookSignatureError):
        _adapter().verify_webhook(_body(_payment(), "someone-else"), {}, CTX)


def test_verify_rejects_a_tampered_field() -> None:
    body = _body(_payment()).replace(b"product_id=768495", b"product_id=768496")
    with pytest.raises(InvalidWebhookSignatureError):
        _adapter().verify_webhook(body, {}, CTX)


def test_verify_rejects_a_missing_signature() -> None:
    with pytest.raises(InvalidWebhookSignatureError):
        _adapter().verify_webhook(_body(_payment(), sign=False), {}, CTX)


def test_verify_rejects_a_non_ascii_signature_without_crashing() -> None:
    # PG-384: an error inside the check must be a rejection, never a crash.
    pairs = list(_payment().items()) + [("sha_sign", "é" * 128)]
    with pytest.raises(InvalidWebhookSignatureError):
        _adapter().verify_webhook(urlencode(pairs).encode(), {}, CTX)


def test_verify_requires_the_passphrase() -> None:
    with pytest.raises(MissingCredentialsError):
        _adapter({"api_key": "123-abc"}).verify_webhook(_body(_payment()), {}, CTX)


# --- mapping --------------------------------------------------------------


def test_payment_grants_access() -> None:
    event = _adapter().parse_event(_body(_payment()), {}, CTX)
    assert event.provider == "digistore24"
    assert event.event_type == "order.paid"
    assert event.provider_event_id == "88001:on_payment"
    assert event.customer.email == "reader@example.com"
    assert event.customer.external_id == "4711"
    assert event.customer.name == "Rea Der"
    assert [(li.external_product_id, li.amount_minor, li.currency) for li in event.line_items] == [
        ("768495", 900, "EUR")
    ]
    assert event.status == "paid"
    assert event.is_test is False


def test_a_renewal_is_its_own_event() -> None:
    first = _adapter().parse_event(_body(_payment()), {}, CTX)
    renewal = _adapter().parse_event(_body(_payment(transaction_id="88002", pay_sequence_no="2")), {}, CTX)
    assert renewal.event_type == "order.paid"
    assert renewal.provider_event_id != first.provider_event_id


def test_test_purchases_are_marked() -> None:
    event = _adapter().parse_event(_body(_payment(api_mode="test")), {}, CTX)
    assert event.is_test is True


@pytest.mark.parametrize("raw", ["last_paid_day", "on_refund", "on_chargeback"])
def test_endings_revoke(raw: str) -> None:
    fields = _payment(event=raw, billing_status="aborted")
    if raw == "last_paid_day":
        fields.pop("transaction_id")
    event = _adapter().parse_event(_body(fields), {}, CTX)
    assert event.event_type == "subscription.revoked"
    assert [li.external_product_id for li in event.line_items] == ["768495"]


def test_last_paid_day_is_identified_by_the_order() -> None:
    fields = _payment(event="last_paid_day")
    fields.pop("transaction_id")
    event = _adapter().parse_event(_body(fields), {}, CTX)
    assert event.provider_event_id == "ABC123XY:last_paid_day"


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("on_rebill_cancelled", "until last_paid_day"),
        ("on_payment_missed", "retries"),
        ("on_rebill_resumed", "next on_payment"),
    ],
)
def test_noted_events_change_nothing_and_say_why(raw: str, reason: str) -> None:
    with pytest.raises(UnsupportedEventTypeError, match=reason):
        _adapter().parse_event(_body(_payment(event=raw)), {}, CTX)


def test_other_events_are_unsupported() -> None:
    adapter = _adapter()
    assert not adapter.supports_raw_event_type("connection_test")
    assert not adapter.supports_raw_event_type("on_affiliation")
    with pytest.raises(UnsupportedEventTypeError):
        adapter.parse_event(_body(_payment(event="connection_test")), {}, CTX)


def test_noted_events_are_stored_not_dropped() -> None:
    adapter = _adapter()
    for raw in ("on_payment", "last_paid_day", "on_refund", "on_chargeback", "on_rebill_cancelled", "on_payment_missed"):
        assert adapter.supports_raw_event_type(raw)


def test_further_items_become_line_items() -> None:
    event = _adapter().parse_event(_body(_payment(product_id_2="768496", product_id_3="768495")), {}, CTX)
    assert [li.external_product_id for li in event.line_items] == ["768495", "768496"]


def test_buyer_email_is_accepted_as_a_fallback() -> None:
    fields = _payment()
    fields.pop("email")
    fields["buyer_email"] = "other@example.com"
    assert _adapter().parse_event(_body(fields), {}, CTX).customer.email == "other@example.com"


def test_missing_email_is_invalid() -> None:
    fields = _payment()
    fields.pop("email")
    with pytest.raises(InvalidWebhookPayloadError):
        _adapter().parse_event(_body(fields), {}, CTX)


def test_missing_product_is_invalid() -> None:
    fields = _payment()
    fields.pop("product_id")
    with pytest.raises(InvalidWebhookPayloadError):
        _adapter().parse_event(_body(fields), {}, CTX)


# --- API key and health check ----------------------------------------------


def test_clean_api_key_drops_terminal_escapes_and_whitespace() -> None:
    assert clean_api_key("\x1b[C123-abcDEF\n") == "123-abcDEF"
    assert clean_api_key("  123-abc\t") == "123-abc"


def test_health_check_reports_the_account_and_never_returns_other_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        digistore24,
        "ds24_call",
        lambda fn, key, params=None: {
            "user_name": "Example Publisher",
            "api_key_permissions": "writable",
            "thankyou_page_key": "secret-must-not-leak",
            "email": "owner@example.com",
        },
    )
    result = _adapter().health_check(CTX)
    assert result["ok"] is True
    assert "Example Publisher" in result["message"]
    assert "secret-must-not-leak" not in repr(result)
    assert "owner@example.com" not in repr(result)


def test_health_check_flags_a_read_only_key(monkeypatch) -> None:
    monkeypatch.setattr(
        digistore24, "ds24_call", lambda fn, key, params=None: {"api_key_permissions": "read-only"}
    )
    result = _adapter().health_check(CTX)
    assert result["ok"] is False
    assert result["code"] == "read_only_key"


def test_health_check_reports_api_errors(monkeypatch) -> None:
    def boom(fn, key, params=None):
        raise RuntimeError("Digistore24 API error: Invalid API key")

    monkeypatch.setattr(digistore24, "ds24_call", boom)
    result = _adapter().health_check(CTX)
    assert result == {"ok": False, "code": "api_error", "message": "Digistore24 API error: Invalid API key"}


def test_health_check_requires_a_key() -> None:
    with pytest.raises(MissingCredentialsError):
        _adapter({"webhook_secret": PASSPHRASE}).health_check(CTX)


# --- real delivery ---------------------------------------------------------

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "digistore24"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_text(encoding="utf-8").strip().encode("utf-8")


def test_real_test_purchase_verifies_and_grants_access() -> None:
    # A monthly subscription bought with Testpay on 18.11.2026 (ipn_version
    # 1.6, 177 fields). Buyer, merchant, addresses, links and keys are
    # replaced, the product name is neutral, and sha_sign is recomputed with
    # the fixture passphrase in Digistore24's byte-wise order.
    body = _fixture("on_payment_test_subscription.txt")
    adapter = _adapter({"webhook_secret": "fixture-passphrase", "api_key": "123-abc"})

    adapter.verify_webhook(body, {}, CTX)
    event = adapter.parse_event(body, {}, CTX)

    assert event.event_type == "order.paid"
    assert event.provider_event_id == "137250455:on_payment"
    assert event.is_test is True
    assert event.customer.email == "reader@example.com"
    assert [(li.external_product_id, li.amount_minor, li.currency) for li in event.line_items] == [
        ("768495", 700, "EUR")
    ]
    assert event.occurred_at == datetime(2026, 11, 18, 11, 52, 9, tzinfo=ZoneInfo("Europe/Berlin"))


def test_real_test_purchase_fails_with_another_passphrase() -> None:
    with pytest.raises(InvalidWebhookSignatureError):
        _adapter().verify_webhook(_fixture("on_payment_test_subscription.txt"), {}, CTX)


def test_real_cancellation_verifies_and_keeps_access() -> None:
    # The buyer stopped the same test subscription on 18.11.2026 through
    # Digistore24's cancellation page: billing_status aborted,
    # billing_stop_reason by_buyer, next_payment_at still a month ahead.
    body = _fixture("on_rebill_cancelled_test_subscription.txt")
    adapter = _adapter({"webhook_secret": "fixture-passphrase", "api_key": "123-abc"})

    adapter.verify_webhook(body, {}, CTX)
    with pytest.raises(UnsupportedEventTypeError, match="until last_paid_day"):
        adapter.parse_event(body, {}, CTX)


def test_real_refund_verifies_and_ends_access() -> None:
    # The buyer asked for a refund of the same test order on 18.11.2026;
    # Digistore24 booked it about a quarter of an hour later.
    body = _fixture("on_refund_test_subscription.txt")
    adapter = _adapter({"webhook_secret": "fixture-passphrase", "api_key": "123-abc"})

    adapter.verify_webhook(body, {}, CTX)
    event = adapter.parse_event(body, {}, CTX)

    assert event.event_type == "subscription.revoked"
    assert event.provider_event_id == "137251579:on_refund"
    assert event.status == "refunded"
    assert event.is_test is True
    assert [li.external_product_id for li in event.line_items] == ["768495"]

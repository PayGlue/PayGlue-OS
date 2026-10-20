# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-337: Lemon Squeezy subscription endings.

The payloads follow Lemon Squeezy's documented webhook shape: meta.event_name,
and data.id is the subscription with its attributes. Two things are pinned
here. Every subscription event gets its own event id, so a cancellation or an
expiry is no longer a duplicate of the purchase. And a cancellation keeps the
access until ends_at; the expiry is what ends it.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from payglue_backend.core.errors import UnsupportedEventTypeError
from payglue_backend.core.idempotency import InMemoryIdempotencyStore
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters.lemon_squeezy import LemonSqueezyPaymentAdapter

NOW = datetime(2023, 1, 20, 12, 0, tzinfo=UTC)


class _Credentials:
    def get_credentials(self, tenant_ctx: TenantContext, provider_key: str) -> dict[str, str]:
        return {"webhook_secret": "whsec"}


def _adapter(now: datetime = NOW) -> LemonSqueezyPaymentAdapter:
    return LemonSqueezyPaymentAdapter(credential_provider=_Credentials(), now=lambda: now)


def _subscription_event(
    event_name: str,
    *,
    status: str,
    updated_at: str,
    ends_at: str | None = None,
    pause: dict | None = None,
    subscription_id: str = "3",
) -> bytes:
    return json.dumps(
        {
            "meta": {"event_name": event_name, "test_mode": True},
            "data": {
                "type": "subscriptions",
                "id": subscription_id,
                "attributes": {
                    "store_id": 2,
                    "customer_id": 2,
                    "order_id": 4,
                    "product_id": 2,
                    "variant_id": 2,
                    "user_name": "John Doe",
                    "user_email": "johndoe@example.com",
                    "status": status,
                    "pause": pause,
                    "cancelled": status == "cancelled",
                    "renews_at": "2023-02-17T14:15:43.000000Z",
                    "ends_at": ends_at,
                    "created_at": "2023-01-17T14:15:45.000000Z",
                    "updated_at": updated_at,
                    "test_mode": True,
                },
            },
        }
    ).encode()


def _parse(raw: bytes, now: datetime = NOW):
    return _adapter(now).parse_event(raw, {}, TenantContext(tenant_slug="tenant-a"))


CREATED = _subscription_event("subscription_created", status="active", updated_at="2023-01-17T14:15:46.000000Z")
CANCELLED = _subscription_event(
    "subscription_cancelled", status="cancelled", updated_at="2023-01-17T18:17:25.000000Z", ends_at="2023-02-17T14:15:43.000000Z"
)
EXPIRED = _subscription_event(
    "subscription_expired", status="expired", updated_at="2023-02-17T14:16:02.000000Z", ends_at="2023-02-17T14:15:43.000000Z"
)


def test_each_subscription_event_has_its_own_event_id() -> None:
    created = _parse(CREATED)
    expired = _parse(EXPIRED, now=datetime(2023, 2, 18, tzinfo=UTC))

    assert created.provider_event_id != expired.provider_event_id
    assert created.provider_event_id.startswith("3:subscription_created:")
    assert expired.provider_event_id.startswith("3:subscription_expired:")


def test_the_same_event_delivered_twice_keeps_one_event_id() -> None:
    assert _parse(CREATED).provider_event_id == _parse(CREATED).provider_event_id


def test_an_expiry_after_the_purchase_is_not_a_duplicate() -> None:
    """The reported case: the expiry used to share the purchase's key and was
    dropped, so the reader kept access for good."""
    store = InMemoryIdempotencyStore()
    for raw, now in ((CREATED, NOW), (EXPIRED, datetime(2023, 2, 18, tzinfo=UTC))):
        event = _parse(raw, now)
        key = f"tenant-a:{event.provider}:{event.provider_event_id}"
        assert store.start_processing(key), f"{event.event_type} was treated as a duplicate"
        store.mark_processed(key)

    redelivered = _parse(CREATED)
    assert not store.start_processing(f"tenant-a:{redelivered.provider}:{redelivered.provider_event_id}")


def test_a_cancellation_keeps_access_until_ends_at() -> None:
    with pytest.raises(UnsupportedEventTypeError, match="2023-02-17"):
        _parse(CANCELLED)


def test_the_update_that_accompanies_a_cancellation_changes_nothing_either() -> None:
    update = _subscription_event(
        "subscription_updated", status="cancelled", updated_at="2023-01-17T18:17:25.000000Z", ends_at="2023-02-17T14:15:43.000000Z"
    )
    with pytest.raises(UnsupportedEventTypeError):
        _parse(update)


def test_a_cancellation_whose_period_has_run_out_ends_access() -> None:
    event = _parse(CANCELLED, now=datetime(2023, 2, 18, tzinfo=UTC))
    assert event.event_type == "subscription.revoked"


def test_a_cancellation_without_an_end_date_waits_for_the_expiry() -> None:
    no_date = _subscription_event("subscription_cancelled", status="cancelled", updated_at="2023-01-17T18:17:25.000000Z")
    with pytest.raises(UnsupportedEventTypeError):
        _parse(no_date)


def test_the_expiry_ends_access() -> None:
    event = _parse(EXPIRED, now=datetime(2023, 2, 18, tzinfo=UTC))
    assert event.event_type == "subscription.revoked"
    assert event.line_items[0].external_product_id == "2"
    assert event.customer.email == "johndoe@example.com"


@pytest.mark.parametrize(
    ("status", "expected"),
    [("active", "subscription.active"), ("on_trial", "subscription.active"), ("expired", "subscription.revoked")],
)
def test_an_update_follows_the_status_it_reports(status: str, expected: str) -> None:
    update = _subscription_event("subscription_updated", status=status, updated_at="2023-01-18T09:00:00.000000Z")
    assert _parse(update).event_type == expected


@pytest.mark.parametrize("status", ["past_due", "unpaid", "paused"])
def test_an_update_during_payment_retries_or_a_pause_changes_nothing(status: str) -> None:
    update = _subscription_event("subscription_updated", status=status, updated_at="2023-01-18T09:00:00.000000Z")
    with pytest.raises(UnsupportedEventTypeError):
        _parse(update)


def test_a_void_pause_ends_access_and_a_free_pause_does_not() -> None:
    void = _subscription_event("subscription_paused", status="paused", updated_at="2023-01-18T09:00:00.000000Z", pause={"mode": "void", "resumes_at": None})
    free = _subscription_event("subscription_paused", status="paused", updated_at="2023-01-18T09:00:00.000000Z", pause={"mode": "free", "resumes_at": None})

    assert _parse(void).event_type == "subscription.canceled"
    with pytest.raises(UnsupportedEventTypeError):
        _parse(free)


def test_a_payment_success_is_skipped_rather_than_failed() -> None:
    """Its data is an invoice without a variant. It used to fail as an invalid
    payload; the subscription events carry the state instead."""
    invoice = json.dumps(
        {
            "meta": {"event_name": "subscription_payment_success"},
            "data": {"type": "subscription-invoices", "id": "77", "attributes": {"subscription_id": 3, "status": "paid", "user_email": "johndoe@example.com"}},
        }
    ).encode()
    with pytest.raises(UnsupportedEventTypeError):
        _parse(invoice)


def test_an_order_keeps_the_order_id_as_its_event_id() -> None:
    """Unchanged, so orders recorded before this fix still match on redelivery."""
    order = json.dumps(
        {
            "meta": {"event_name": "order_created"},
            "data": {
                "type": "orders",
                "id": "9253484",
                "attributes": {
                    "user_email": "johndoe@example.com",
                    "user_name": "John Doe",
                    "currency": "EUR",
                    "status": "paid",
                    "created_at": "2023-01-17T14:15:45.000000Z",
                    "first_order_item": {"variant_id": 5, "price": 900},
                },
            },
        }
    ).encode()

    event = _parse(order)

    assert event.provider_event_id == "9253484"
    assert event.event_type == "order.paid"


# -- Real test-mode payloads --------------------------------------------------
# Captured on staging on 2026-10-20 from a Lemon Squeezy test-mode store: a
# subscription bought, renewed once, then cancelled with immediate effect,
# which Lemon Squeezy reports as subscription_cancelled with status expired
# and ends_at set to the moment of cancellation. Email, name and signed links
# are replaced; everything else is as Lemon Squeezy sent it.

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "lemon_squeezy"
AFTER_THE_END = datetime(2026, 10, 20, 21, 10, 40, tzinfo=UTC)
DURING_THE_PERIOD = datetime(2026, 10, 20, 20, 58, tzinfo=UTC)


def _real(name: str) -> bytes:
    return (_FIXTURES / f"{name}.json").read_bytes()


def test_real_purchase_grants_and_each_event_has_its_own_id() -> None:
    created = _parse(_real("subscription_created"), DURING_THE_PERIOD)
    renewed = _parse(_real("subscription_updated_active"), DURING_THE_PERIOD)

    assert created.event_type == renewed.event_type == "subscription.active"
    assert created.line_items[0].external_product_id == "2274371"
    assert created.customer.email == "reader@example.com"
    assert created.is_test
    assert created.provider_event_id != renewed.provider_event_id


def test_real_immediate_cancellation_and_expiry_both_end_access() -> None:
    cancelled = _parse(_real("subscription_cancelled_immediately"), AFTER_THE_END)
    updated = _parse(_real("subscription_updated_expired"), AFTER_THE_END)
    expired = _parse(_real("subscription_expired"), AFTER_THE_END)

    assert {cancelled.event_type, updated.event_type, expired.event_type} == {"subscription.revoked"}
    ids = {cancelled.provider_event_id, updated.provider_event_id, expired.provider_event_id}
    assert len(ids) == 3, "none of the endings is a duplicate of another"


def test_real_sequence_is_never_dropped_as_duplicate() -> None:
    """The whole recorded lifecycle through one idempotency store, the way the
    orchestrator sees it. Before the fix only the first subscription event
    got through."""
    store = InMemoryIdempotencyStore()
    sequence = [
        ("order_created", DURING_THE_PERIOD),
        ("subscription_created", DURING_THE_PERIOD),
        ("subscription_updated_active", DURING_THE_PERIOD),
        ("subscription_cancelled_immediately", AFTER_THE_END),
        ("subscription_expired", AFTER_THE_END),
    ]
    for name, now in sequence:
        event = _parse(_real(name), now)
        key = f"tenant-a:{event.provider}:{event.provider_event_id}"
        assert store.start_processing(key), f"{name} was dropped as a duplicate"
        store.mark_processed(key)


def test_real_order_keeps_its_order_id() -> None:
    event = _parse(_real("order_created"), DURING_THE_PERIOD)
    assert event.event_type == "order.paid"
    assert event.provider_event_id == "9811494"


def test_real_payment_success_is_skipped() -> None:
    with pytest.raises(UnsupportedEventTypeError):
        _parse(_real("subscription_payment_success"), DURING_THE_PERIOD)

"""PayPal cancellations keep access until the paid period ends (PG-368).

The deliveries follow the subscription object PayPal documents for
BILLING.SUBSCRIPTION.CANCELLED; the subscription and plan reads are stubbed.
"""
import json
from datetime import UTC, datetime

import pytest

from payglue_backend.core.errors import AccessRunsUntilError
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters.paypal import PayPalPaymentAdapter, _add_interval

TENANT = TenantContext(tenant_slug="tenant-a")
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


class StubCredentialProvider:
    def get_credentials(self, tenant_ctx, provider_key):
        return {"client_id": "id", "client_secret": "secret", "webhook_id": "wh", "sandbox": "true"}


def _adapter(api: dict[str, dict] | None = None, calls: list[str] | None = None) -> PayPalPaymentAdapter:
    adapter = PayPalPaymentAdapter(credential_provider=StubCredentialProvider(), now=lambda: NOW)

    def fake_get(tenant_ctx, path):
        if calls is not None:
            calls.append(path)
        return (api or {})[path]

    adapter._api_get = fake_get
    return adapter


def _cancelled(billing_info: dict | None) -> bytes:
    resource = {
        "id": "I-TEST",
        "plan_id": "P-TEST",
        "status": "CANCELLED",
        "subscriber": {"email_address": "reader@example.com", "name": {"given_name": "Sam", "surname": "Reader"}},
    }
    if billing_info is not None:
        resource["billing_info"] = billing_info
    return json.dumps(
        {
            "id": "WH-TEST",
            "event_type": "BILLING.SUBSCRIPTION.CANCELLED",
            "create_time": "2026-11-04T11:00:00Z",
            "resource": resource,
        }
    ).encode()


def test_a_cancellation_with_a_next_billing_time_keeps_access_until_then() -> None:
    adapter = _adapter()

    with pytest.raises(AccessRunsUntilError) as raised:
        adapter.parse_event(_cancelled({"next_billing_time": "2026-11-20T10:00:00Z"}), {}, TENANT)

    assert raised.value.ends_at == datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    end = json.loads(raised.value.end_payload)
    assert end["event_type"] == "BILLING.SUBSCRIPTION.EXPIRED"
    assert end["id"] == "WH-TEST:period-end"
    assert end["resource"]["id"] == "I-TEST"


def test_without_a_next_billing_time_the_period_follows_the_last_payment_and_the_plan() -> None:
    calls: list[str] = []
    plan = {
        "billing_cycles": [
            {"tenure_type": "TRIAL", "frequency": {"interval_unit": "DAY", "interval_count": 7}},
            {"tenure_type": "REGULAR", "frequency": {"interval_unit": "MONTH", "interval_count": 1}},
        ]
    }
    adapter = _adapter({"/v1/billing/plans/P-TEST": plan}, calls)

    with pytest.raises(AccessRunsUntilError) as raised:
        adapter.parse_event(_cancelled({"last_payment": {"time": "2026-10-28T09:00:00Z"}}), {}, TENANT)

    assert raised.value.ends_at == datetime(2026, 11, 28, 9, 0, tzinfo=UTC)
    assert calls == ["/v1/billing/plans/P-TEST"]


def test_a_thin_delivery_reads_the_subscription_first() -> None:
    calls: list[str] = []
    subscription = {"id": "I-TEST", "plan_id": "P-TEST", "billing_info": {"next_billing_time": "2026-12-01T00:00:00Z"}}
    adapter = _adapter({"/v1/billing/subscriptions/I-TEST": subscription}, calls)

    with pytest.raises(AccessRunsUntilError) as raised:
        adapter.parse_event(_cancelled(None), {}, TENANT)

    assert raised.value.ends_at == datetime(2026, 12, 1, tzinfo=UTC)
    assert calls == ["/v1/billing/subscriptions/I-TEST"]


def test_a_cancellation_whose_period_has_run_out_ends_access_now() -> None:
    adapter = _adapter()

    event = adapter.parse_event(_cancelled({"next_billing_time": "2026-11-01T00:00:00Z"}), {}, TENANT)

    assert event.event_type == "subscription.revoked"
    assert event.customer.email == "reader@example.com"


def test_without_any_date_access_ends_now() -> None:
    """PayPal sends nothing later, so keeping access here would keep it forever."""
    adapter = _adapter({"/v1/billing/subscriptions/I-TEST": {"id": "I-TEST", "plan_id": "P-TEST"}})

    event = adapter.parse_event(_cancelled(None), {}, TENANT)

    assert event.event_type == "subscription.revoked"


def test_the_scheduled_end_revokes_under_its_own_id() -> None:
    adapter = _adapter()
    with pytest.raises(AccessRunsUntilError) as raised:
        adapter.parse_event(_cancelled({"next_billing_time": "2026-11-20T10:00:00Z"}), {}, TENANT)

    event = adapter.parse_event(raised.value.end_payload, {}, TENANT)

    assert event.event_type == "subscription.revoked"
    assert event.provider_event_id == "WH-TEST:period-end"
    assert event.line_items[0].external_product_id == "P-TEST"


def test_a_resumed_subscription_is_recognised() -> None:
    adapter = _adapter({"/v1/billing/subscriptions/I-TEST": {"status": "ACTIVE"}})

    assert adapter.subscription_is_active(TENANT, _cancelled(None)) is True


@pytest.mark.parametrize(
    ("start", "unit", "count", "expected"),
    [
        (datetime(2026, 1, 31, tzinfo=UTC), "MONTH", 1, datetime(2026, 2, 28, tzinfo=UTC)),
        (datetime(2026, 11, 3, tzinfo=UTC), "YEAR", 1, datetime(2027, 11, 3, tzinfo=UTC)),
        (datetime(2026, 11, 3, tzinfo=UTC), "WEEK", 2, datetime(2026, 11, 17, tzinfo=UTC)),
        (datetime(2026, 12, 15, tzinfo=UTC), "MONTH", 3, datetime(2027, 3, 15, tzinfo=UTC)),
    ],
)
def test_billing_cycles(start, unit, count, expected) -> None:
    assert _add_interval(start, unit, count) == expected

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from payglue_backend.core.errors import AccessRunsUntilError, UnsupportedEventTypeError
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters.gumroad import GumroadPaymentAdapter

CURRENT = "https://api.example.com/webhooks/gumroad?tenant=tenant-a&key=new"
OLD = "https://api.example.com/webhooks/gumroad?tenant=tenant-a"


class StubCredentialProvider:
    def get_credentials(self, tenant_ctx: TenantContext, provider_key: str) -> dict[str, str]:
        return {"access_token": "token", "application_secret": "secret"}


class FakeGumroad:
    """Answers the resource_subscriptions calls and records them."""

    def __init__(self, existing: dict[str, list[dict]]) -> None:
        self.existing = existing
        self.calls: list[tuple[str, str, dict]] = []

    def urlopen(self, req, timeout=None):
        url = urlparse(req.full_url)
        params = parse_qs(req.data.decode() if req.data else url.query)
        flat = {key: values[0] for key, values in params.items()}
        self.calls.append((req.get_method(), url.path, flat))
        if req.get_method() == "GET":
            body = {"success": True, "resource_subscriptions": self.existing.get(flat["resource_name"], [])}
        else:
            body = {"success": True}
        return _Response(body)


class _Response:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


@pytest.fixture
def adapter() -> GumroadPaymentAdapter:
    return GumroadPaymentAdapter(credential_provider=StubCredentialProvider())


def test_registration_uses_put(adapter, monkeypatch) -> None:
    fake = FakeGumroad({})
    monkeypatch.setattr("urllib.request.urlopen", fake.urlopen)

    result = adapter.register_webhook_subscriptions(TenantContext(tenant_slug="tenant-a"), CURRENT)

    assert result == {"registered": ["sale", "cancellation", "subscription_ended"], "failed": []}
    created = [call for call in fake.calls if call[0] == "PUT"]
    assert [call[2]["resource_name"] for call in created] == ["sale", "cancellation", "subscription_ended"]
    assert all(call[1] == "/v2/resource_subscriptions" and call[2]["post_url"] == CURRENT for call in created)


def test_registration_replaces_an_older_address_of_the_same_tenant(adapter, monkeypatch) -> None:
    fake = FakeGumroad(
        {
            "sale": [
                {"id": "old-sale", "post_url": OLD},
                {"id": "other-tenant", "post_url": "https://api.example.com/webhooks/gumroad?tenant=tenant-b"},
                {"id": "foreign", "post_url": "https://hooks.example.org/gumroad?tenant=tenant-a"},
            ],
            "cancellation": [{"id": "old-cancel", "post_url": OLD}],
            "subscription_ended": [
                {"id": "internal-host", "post_url": "https://internal.example.net/webhooks/gumroad?tenant=tenant-a&key=new"}
            ],
        }
    )
    monkeypatch.setattr("urllib.request.urlopen", fake.urlopen)

    adapter.register_webhook_subscriptions(TenantContext(tenant_slug="tenant-a"), CURRENT)

    deleted = [call[1] for call in fake.calls if call[0] == "DELETE"]
    assert deleted == [
        "/v2/resource_subscriptions/old-sale",
        "/v2/resource_subscriptions/old-cancel",
        "/v2/resource_subscriptions/internal-host",
    ]


def test_registration_keeps_a_current_subscription(adapter, monkeypatch) -> None:
    fake = FakeGumroad({"sale": [{"id": "current", "post_url": CURRENT}, {"id": "twin", "post_url": CURRENT}]})
    monkeypatch.setattr("urllib.request.urlopen", fake.urlopen)

    result = adapter.register_webhook_subscriptions(TenantContext(tenant_slug="tenant-a"), CURRENT)

    assert "sale" in result["registered"]
    assert [call[1] for call in fake.calls if call[0] == "DELETE"] == ["/v2/resource_subscriptions/twin"]
    assert [call[2]["resource_name"] for call in fake.calls if call[0] == "PUT"] == [
        "cancellation",
        "subscription_ended",
    ]


def test_registration_reports_a_failed_resource(adapter, monkeypatch) -> None:
    def broken(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr("urllib.request.urlopen", broken)

    result = adapter.register_webhook_subscriptions(TenantContext(tenant_slug="tenant-a"), CURRENT)

    assert result == {"registered": [], "failed": ["sale", "cancellation", "subscription_ended"]}


# --- subscription lifecycle --------------------------------------------------

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "gumroad"
_FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def _cancellation(**overrides: str) -> bytes:
    from urllib.parse import parse_qsl, urlencode

    fields = dict(parse_qsl((_FIXTURES / "cancellation.txt").read_text(), keep_blank_values=True))
    fields.update(overrides)
    return urlencode(fields).encode()


def _adapter_at(when: datetime) -> GumroadPaymentAdapter:
    return GumroadPaymentAdapter(credential_provider=StubCredentialProvider(), now=lambda: when)


def test_a_cancellation_keeps_access_until_the_paid_period_ends() -> None:
    """The real payload: cancelled the day after a yearly purchase, so access
    runs for another year and subscription_ended takes it away then."""
    adapter = _adapter_at(datetime(2026, 11, 4, tzinfo=UTC))

    with pytest.raises(UnsupportedEventTypeError, match="2027-11-03"):
        adapter.parse_event(_cancellation(), _FORM, TenantContext(tenant_slug="tenant-a"))


def test_a_cancellation_queues_its_own_end_on_the_cancellation_date() -> None:
    """subscription_ended has not been seen live, so access must not depend
    on it alone: the cancellation hands over an end for cancelled_at."""
    adapter = _adapter_at(datetime(2026, 11, 4, tzinfo=UTC))

    with pytest.raises(AccessRunsUntilError) as raised:
        adapter.parse_event(_cancellation(), _FORM, TenantContext(tenant_slug="tenant-a"))

    fields = dict(parse_qs(raised.value.end_payload.decode()))
    assert raised.value.ends_at.date().isoformat() == "2027-11-03"
    assert fields["resource_name"] == ["subscription_ended"]
    assert "cancelled" not in fields and "cancelled_at" not in fields


def test_a_real_subscription_ended_ends_access() -> None:
    """The real payload, seen when three trial memberships ran out on
    10 November 2026: ended_at and ended_reason, no cancelled fields."""
    adapter = _adapter_at(datetime(2026, 11, 10, 14, tzinfo=UTC))

    event = adapter.parse_event(
        (_FIXTURES / "subscription_ended.txt").read_bytes(), _FORM, TenantContext(tenant_slug="tenant-a")
    )

    assert event.event_type == "subscription.revoked"
    assert event.provider_event_id == "sub_TEST==:ended"
    assert event.customer.email == "reader@example.com"
    assert event.line_items[0].external_product_id == "prod_TEST=="


def test_the_queued_end_and_subscription_ended_are_one_event() -> None:
    """Keyed alike, so whichever arrives first ends access and the other is a
    duplicate rather than a second revocation."""
    adapter = _adapter_at(datetime(2026, 11, 4, tzinfo=UTC))
    with pytest.raises(AccessRunsUntilError) as raised:
        adapter.parse_event(_cancellation(), _FORM, TenantContext(tenant_slug="tenant-a"))
    later = _adapter_at(datetime(2027, 11, 4, tzinfo=UTC))
    real_end = (_FIXTURES / "subscription_ended.txt").read_bytes()

    # A queued event keeps no headers, so the end must parse without them.
    queued = later.parse_event(raised.value.end_payload, {}, TenantContext(tenant_slug="tenant-a"))
    real = later.parse_event(real_end, _FORM, TenantContext(tenant_slug="tenant-a"))

    assert queued.event_type == real.event_type == "subscription.revoked"
    assert queued.provider_event_id == real.provider_event_id == "sub_TEST==:ended"
    assert queued.customer.email == "reader@example.com"


def test_a_test_cancellation_queues_a_test_end() -> None:
    adapter = _adapter_at(datetime(2026, 11, 4, tzinfo=UTC))
    with pytest.raises(AccessRunsUntilError) as raised:
        adapter.parse_event(_cancellation(test="true"), _FORM, TenantContext(tenant_slug="tenant-a"))

    later = _adapter_at(datetime(2027, 11, 4, tzinfo=UTC))
    assert later.parse_event(raised.value.end_payload, {}, TenantContext(tenant_slug="tenant-a")).is_test


class _Subscriber:
    def __init__(self, status: str) -> None:
        self.status = status
        self.paths: list[str] = []

    def urlopen(self, req, timeout=None):
        self.paths.append(urlparse(req.full_url).path)
        return _Response({"success": True, "subscriber": {"status": self.status}})


@pytest.mark.parametrize("status, active", [("alive", True), ("cancelled", False), ("pending_cancellation", False)])
def test_a_restarted_membership_counts_as_active(monkeypatch, status, active) -> None:
    gumroad = _Subscriber(status)
    monkeypatch.setattr("urllib.request.urlopen", gumroad.urlopen)
    adapter = _adapter_at(datetime(2027, 11, 4, tzinfo=UTC))

    result = adapter.subscription_is_active(TenantContext(tenant_slug="tenant-a"), _cancellation())

    assert result is active
    assert gumroad.paths == ["/v2/subscribers/sub_TEST=="]


def test_a_cancellation_whose_period_has_run_out_ends_access() -> None:
    adapter = _adapter_at(datetime(2027, 11, 4, tzinfo=UTC))

    event = adapter.parse_event(_cancellation(), _FORM, TenantContext(tenant_slug="tenant-a"))

    assert event.event_type == "subscription.revoked"
    assert event.customer.email == "reader@example.com"
    assert event.provider_event_id == "sub_TEST==:cancelled"
    assert event.line_items[0].external_product_id == "prod_TEST=="


def test_a_cancellation_without_a_date_keeps_access() -> None:
    adapter = _adapter_at(datetime(2027, 11, 4, tzinfo=UTC))

    with pytest.raises(UnsupportedEventTypeError):
        adapter.parse_event(_cancellation(cancelled_at=""), _FORM, TenantContext(tenant_slug="tenant-a"))


def test_the_end_of_a_subscription_is_not_a_duplicate_of_its_cancellation() -> None:
    """Both carry the same subscription_id. Keyed on it alone, the end was
    dropped as a duplicate and access never ended."""
    adapter = _adapter_at(datetime(2026, 11, 4, tzinfo=UTC))
    ended = _cancellation(resource_name="subscription_ended", cancelled="", cancelled_at="")

    event = adapter.parse_event(ended, _FORM, TenantContext(tenant_slug="tenant-a"))

    assert event.event_type == "subscription.revoked"
    assert event.provider_event_id == "sub_TEST==:ended"

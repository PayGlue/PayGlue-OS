"""Scheduled ends of a paid period, for providers that send nothing then (PG-368)."""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.core.errors import AccessRunsUntilError
from payglue_backend.tenants.models import Tenant
from payglue_backend.webhooks import period_ends, tasks
from payglue_backend.webhooks.models import WebhookInboundEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def cancellation() -> WebhookInboundEvent:
    Tenant.objects.create(schema_name="acme", slug="acme")
    return WebhookInboundEvent.objects.create(
        tenant_slug="acme",
        provider="paypal",
        status=WebhookInboundEvent.Status.RECEIVED,
        payload_raw=b'{"id": "WH-1", "event_type": "BILLING.SUBSCRIPTION.CANCELLED"}',
        endpoint_path="/t/acme/webhooks/paypal/[redacted]/",
    )


def _runs_until(days: int) -> AccessRunsUntilError:
    return AccessRunsUntilError(
        "cancellation runs to the end of the paid period",
        ends_at=timezone.now() + timedelta(days=days),
        end_payload=b'{"id": "WH-1:period-end", "event_type": "BILLING.SUBSCRIPTION.EXPIRED"}',
    )


class _Orchestrator:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def process_webhook(self, **kwargs):
        raise self.error


def test_a_skipped_cancellation_leaves_its_end_behind(cancellation, monkeypatch) -> None:
    error = _runs_until(16)
    monkeypatch.setattr(tasks.wiring, "get_webhook_orchestrator", lambda: _Orchestrator(error))
    monkeypatch.setattr(tasks.wiring, "get_tenant_cms_provider_key", lambda slug: "ghost")

    tasks.process_inbound_webhook_event(cancellation.id)

    cancellation.refresh_from_db()
    assert cancellation.status == WebhookInboundEvent.Status.SKIPPED
    end = WebhookInboundEvent.objects.exclude(pk=cancellation.pk).get()
    assert end.status == WebhookInboundEvent.Status.RECEIVED
    assert end.next_attempt_at == error.ends_at
    assert end.payload_snapshot["event_type"] == "BILLING.SUBSCRIPTION.EXPIRED"
    assert end.endpoint_metadata == {period_ends.SCHEDULED_END_OF: cancellation.id}


def test_a_replayed_cancellation_does_not_queue_a_second_end(cancellation) -> None:
    first = period_ends.schedule(cancellation, _runs_until(16))
    second = period_ends.schedule(cancellation, _runs_until(16))

    assert first.pk == second.pk
    assert WebhookInboundEvent.objects.count() == 2


def test_only_ends_that_are_due_are_processed(cancellation, monkeypatch) -> None:
    due = period_ends.schedule(cancellation, _runs_until(-1))
    later = period_ends.schedule(
        WebhookInboundEvent.objects.create(
            tenant_slug="acme", provider="paypal", status=WebhookInboundEvent.Status.SKIPPED,
            payload_raw=b"{}", endpoint_path="/t/acme/webhooks/paypal/[redacted]/",
        ),
        _runs_until(10),
    )
    processed: list[int] = []
    monkeypatch.setattr(period_ends, "still_active", lambda event: False)
    monkeypatch.setattr(
        "payglue_backend.tenants.management.commands.end_paid_periods.process_inbound_webhook_event",
        lambda event_id, **kwargs: processed.append((event_id, kwargs)),
    )

    call_command("end_paid_periods")

    assert processed == [(due.id, {"ignore_timing": True, "skip_verification": True})]
    later.refresh_from_db()
    assert later.status == WebhookInboundEvent.Status.RECEIVED


def test_a_resumed_subscription_keeps_access(cancellation, monkeypatch) -> None:
    due = period_ends.schedule(cancellation, _runs_until(-1))
    monkeypatch.setattr(period_ends, "still_active", lambda event: True)

    call_command("end_paid_periods")

    due.refresh_from_db()
    assert due.status == WebhookInboundEvent.Status.SKIPPED
    assert "resumed" in due.last_error


def test_an_unreachable_provider_waits_for_the_next_night(cancellation, monkeypatch) -> None:
    due = period_ends.schedule(cancellation, _runs_until(-1))

    def unreachable(event):
        raise RuntimeError("timeout")

    monkeypatch.setattr(period_ends, "still_active", unreachable)

    call_command("end_paid_periods")

    due.refresh_from_db()
    assert due.status == WebhookInboundEvent.Status.RECEIVED

"""PG-402: one delivery state, built from the paths that write the rows.

Every row here is produced by the worker, period_ends.schedule() or the real
Digistore24 adapter with a recorded delivery, not written by hand, so the test
follows the code that sets status, next_attempt_at and the flags."""
import pathlib
from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from payglue_backend.core.errors import (
    AccessRunsUntilError,
    CmsApplyEntitlementError,
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
)
from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile
from payglue_backend.webhooks import delivery_state, period_ends, tasks
from payglue_backend.webhooks.models import WebhookInboundEvent

pytestmark = pytest.mark.django_db

_S = WebhookInboundEvent.Status
FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "digistore24"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_text(encoding="utf-8").strip().encode("utf-8")


@pytest.fixture(autouse=True)
def _tenant(settings, monkeypatch) -> None:
    settings.CELERY_TASK_ALWAYS_EAGER = False
    Tenant.objects.create(schema_name="acme", slug="acme")
    monkeypatch.setattr(tasks.wiring, "get_tenant_cms_provider_key", lambda slug: "ghost")
    # A retry is queued, not run: the row stays as the failed attempt left it.
    monkeypatch.setattr(
        tasks.process_inbound_webhook_event, "apply_async", lambda *args, **kwargs: None
    )
    # The alert mail is covered elsewhere; here it would only need an owner.
    monkeypatch.setattr(tasks.delivery_alerts, "record_delivery_failure", lambda *a, **k: None)


class _Orchestrator:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def process_webhook(self, **kwargs):
        raise self.error


def _receive(
    payload: bytes = b"{}",
    provider: str = "digistore24",
    max_attempts: int = 5,
    **fields,
) -> WebhookInboundEvent:
    return WebhookInboundEvent.objects.create(
        tenant_slug="acme",
        provider=provider,
        status=_S.RECEIVED,
        max_attempts=max_attempts,
        payload_raw=payload,
        endpoint_path=f"/t/acme/webhooks/{provider}/[redacted]/",
        **fields,
    )


def _run(event: WebhookInboundEvent, monkeypatch, error: Exception | None = None) -> WebhookInboundEvent:
    if error is not None:
        monkeypatch.setattr(tasks.wiring, "get_webhook_orchestrator", lambda: _Orchestrator(error))
    tasks.process_inbound_webhook_event(event.id)
    event.refresh_from_db()
    return event


def _ghost_down() -> CmsApplyEntitlementError:
    return CmsApplyEntitlementError("Timed out contacting Ghost Admin API")


# --- the cases from the brief --------------------------------------------------


def test_a_scheduled_period_end_is_planned_work_not_a_retry(monkeypatch) -> None:
    cancellation = _receive(b'{"id": "WH-1"}', provider="paypal")
    error = AccessRunsUntilError(
        "cancellation runs to the end of the paid period",
        ends_at=timezone.now() + timedelta(days=16),
        end_payload=b'{"id": "WH-1:period-end", "event_type": "BILLING.SUBSCRIPTION.EXPIRED"}',
    )
    _run(cancellation, monkeypatch, error)
    end = WebhookInboundEvent.objects.exclude(pk=cancellation.pk).get()

    assert end.status == _S.RECEIVED
    assert end.next_attempt_at > timezone.now()
    assert end.delivery_state == delivery_state.SCHEDULED
    assert cancellation.delivery_state == delivery_state.SKIPPED
    summary = delivery_state.summary("acme")
    assert summary["counts"][delivery_state.SCHEDULED] == 1
    assert summary["counts"][delivery_state.NEEDS_YOU] == 0
    assert summary["counts"][delivery_state.RETRYING] == 0


def test_a_period_end_that_is_due_stays_scheduled_until_the_nightly_job(monkeypatch) -> None:
    # The System page used to call this "stuck" ten minutes after its day came,
    # although the nightly job is what runs it.
    cancellation = _receive(b'{"id": "WH-2"}', provider="paypal")
    due = period_ends.schedule(
        cancellation,
        AccessRunsUntilError(
            "ends",
            ends_at=timezone.now() - timedelta(hours=5),
            end_payload=b'{"id": "WH-2:period-end"}',
        ),
    )
    assert due.delivery_state == delivery_state.SCHEDULED
    assert not delivery_state.needs_you().exists()


def test_a_failure_with_a_queued_next_attempt_is_retrying(monkeypatch) -> None:
    event = _run(_receive(_fixture("on_payment_test_subscription.txt")), monkeypatch, _ghost_down())

    assert event.status == _S.FAILED
    assert event.attempts == 1
    assert event.next_attempt_at > timezone.now()
    assert event.delivery_state == delivery_state.RETRYING
    assert delivery_state.summary("acme")["counts"][delivery_state.RETRYING] == 1


def test_a_retry_nobody_picked_up_needs_you(monkeypatch) -> None:
    event = _run(_receive(), monkeypatch, _ghost_down())
    later = event.next_attempt_at + delivery_state.RETRY_GRACE + timedelta(minutes=1)

    assert delivery_state.classify(event, later) == delivery_state.NEEDS_YOU


def test_exhausted_attempts_need_you(monkeypatch) -> None:
    event = _run(_receive(max_attempts=1), monkeypatch, _ghost_down())

    assert event.status == _S.DEAD_LETTER
    assert event.delivery_state == delivery_state.NEEDS_YOU


def test_a_failure_with_no_retry_scheduled_needs_you(monkeypatch) -> None:
    # 3 of 5 attempts and no next one, as on the demo tenant.
    event = _receive(attempts=2)
    event = _run(event, monkeypatch, InvalidWebhookPayloadError("missing email"))

    assert event.status == _S.FAILED
    assert (event.attempts, event.max_attempts, event.next_attempt_at) == (3, 5, None)
    assert event.delivery_state == delivery_state.NEEDS_YOU
    [group] = delivery_state.summary("acme")["needs_you"]
    assert (group["provider"], group["count"], group["attempts"], group["max_attempts"]) == (
        "digistore24",
        1,
        3,
        5,
    )


def test_a_paused_tenant_leaves_a_failure_that_needs_you(monkeypatch) -> None:
    Tenant.objects.filter(slug="acme").update(status=Tenant.Status.PAUSED)
    event = _run(_receive(), monkeypatch)

    assert event.status == _S.FAILED
    assert event.delivery_state == delivery_state.NEEDS_YOU


def test_a_noted_digistore24_event_is_skipped_not_needs_you(monkeypatch) -> None:
    # The real adapter with the recorded on_rebill_cancelled delivery. Its
    # signature counts as checked, so the worker goes straight to parsing.
    event = _receive(_fixture("on_rebill_cancelled_test_subscription.txt"), signature_verified=True)
    event = _run(event, monkeypatch)

    assert event.status == _S.SKIPPED
    assert "access continues" in event.last_error
    assert event.delivery_state == delivery_state.SKIPPED
    assert not delivery_state.needs_you().exists()


def test_a_rejected_signature_is_its_own_state(monkeypatch) -> None:
    event = _run(_receive(), monkeypatch, InvalidWebhookSignatureError("signature mismatch"))

    assert event.status == _S.FAILED
    assert event.verification_failed is True
    assert event.next_attempt_at is None
    assert event.delivery_state == delivery_state.REJECTED
    assert not delivery_state.needs_you().exists()


def test_a_failed_test_purchase_is_marked_and_kept_out_of_needs_you(monkeypatch) -> None:
    # The recorded Digistore24 delivery is a Testpay purchase (api_mode=test).
    event = _run(
        _receive(_fixture("on_payment_test_subscription.txt"), max_attempts=1),
        monkeypatch,
        _ghost_down(),
    )

    assert event.status == _S.DEAD_LETTER
    assert event.endpoint_metadata[delivery_state.TEST_MARKER] is True
    assert event.delivery_state == delivery_state.TEST
    assert not delivery_state.needs_you().exists()


def test_a_live_purchase_that_fails_is_not_marked_as_a_test(monkeypatch) -> None:
    live = _fixture("on_payment_test_subscription.txt").replace(b"api_mode=test", b"api_mode=live")
    event = _run(_receive(live, max_attempts=1), monkeypatch, _ghost_down())

    assert delivery_state.TEST_MARKER not in event.endpoint_metadata
    assert event.delivery_state == delivery_state.NEEDS_YOU


def test_delivered_and_in_flight(monkeypatch) -> None:
    class _Ok:
        def process_webhook(self, **kwargs):
            return type("R", (), {"status": "processed", "event_id": "x"})()

    monkeypatch.setattr(tasks.wiring, "get_webhook_orchestrator", lambda: _Ok())
    delivered = _run(_receive(), monkeypatch)
    waiting = _receive()

    assert delivered.delivery_state == delivery_state.DELIVERED
    assert waiting.delivery_state == delivery_state.IN_FLIGHT


def test_an_old_stuck_delivery_counts_where_it_is_listed(monkeypatch) -> None:
    """The card once counted seven days while the events list showed them all,
    so a stuck delivery older than a week read "Every purchase reached Ghost"
    on the card and "Needs you" in the list. Same rows for both now."""
    event = _run(_receive(max_attempts=1), monkeypatch, _ghost_down())
    WebhookInboundEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - timedelta(days=40))

    listed = [e for e in WebhookInboundEvent.objects.all() if e.delivery_state == delivery_state.NEEDS_YOU]
    assert delivery_state.summary("acme")["counts"][delivery_state.NEEDS_YOU] == len(listed) == 1
    assert delivery_state.needs_you().count() == 1


# --- one rule, three readers ------------------------------------------------------


def test_classify_the_filters_and_the_annotation_agree(monkeypatch) -> None:
    """The Python rule, the queryset filters and the annotation are the same
    predicate. Run all three over one row of every kind."""
    # First, while the worker still has the real orchestrator: skipped.
    _run(_receive(_fixture("on_rebill_cancelled_test_subscription.txt"), signature_verified=True), monkeypatch)
    _run(_receive(), monkeypatch, _ghost_down())  # retrying
    _run(_receive(max_attempts=1), monkeypatch, _ghost_down())  # needs_you, dead letter
    _run(_receive(attempts=2), monkeypatch, InvalidWebhookPayloadError("x"))  # needs_you, failed
    _run(_receive(), monkeypatch, InvalidWebhookSignatureError("x"))  # rejected
    _run(
        _receive(_fixture("on_payment_test_subscription.txt"), max_attempts=1),
        monkeypatch,
        _ghost_down(),
    )  # test
    _receive()  # in flight
    period_ends.schedule(
        _receive(provider="paypal"),
        AccessRunsUntilError("x", ends_at=timezone.now() + timedelta(days=3), end_payload=b"{}"),
    )
    overdue = _run(_receive(), monkeypatch, _ghost_down())
    WebhookInboundEvent.objects.filter(pk=overdue.pk).update(
        next_attempt_at=timezone.now() - timedelta(hours=1)
    )

    now = timezone.now()
    events = list(WebhookInboundEvent.objects.all())
    by_python = {event.pk: delivery_state.classify(event, now) for event in events}
    by_filter = {}
    for state in delivery_state.STATES:
        for pk in WebhookInboundEvent.objects.filter(delivery_state.state_q(state, now)).values_list(
            "pk", flat=True
        ):
            assert pk not in by_filter, f"event {pk} matches two states"
            by_filter[pk] = state
    by_annotation = dict(
        WebhookInboundEvent.objects.annotate(s=delivery_state.state_expression(now)).values_list("pk", "s")
    )

    assert by_python == by_filter == by_annotation
    assert set(by_python.values()) == set(delivery_state.STATES) - {delivery_state.DELIVERED}


# --- the endpoint the dashboard reads --------------------------------------------


@dataclass(frozen=True)
class _Claims:
    firebase_uid: str
    email: str


def test_the_health_endpoint_is_scoped_to_the_tenant(monkeypatch) -> None:
    tenant = Tenant.objects.get(slug="acme")
    Tenant.objects.create(schema_name="other", slug="other")
    profile = UserProfile.objects.create(firebase_uid="uid-health", email="health@example.com")
    TenantMembership.objects.create(
        tenant=tenant, user_profile=profile, role=TenantMembership.Role.SUPPORT_READONLY
    )

    class _Verifier:
        def verify(self, token):
            return _Claims(firebase_uid=profile.firebase_uid, email=profile.email)

    monkeypatch.setattr("payglue_backend.authn.authentication.get_auth_token_verifier", lambda: _Verifier())
    _run(_receive(attempts=2), monkeypatch, InvalidWebhookPayloadError("missing email"))
    WebhookInboundEvent.objects.create(
        tenant_slug="other", provider="polar", status=_S.DEAD_LETTER, payload_raw=b"{}", endpoint_path="/x/"
    )

    response = Client().get("/t/acme/api/v1/events/health", HTTP_AUTHORIZATION="Bearer stub.header.signature")

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["needs_you"] == 1
    assert body["providers"]["digistore24"]["needs_you"] == 1
    assert "polar" not in body["providers"]
    assert body["needs_you"][0]["attempts"] == 3

    events = Client().get("/t/acme/api/v1/events", HTTP_AUTHORIZATION="Bearer stub.header.signature").json()
    assert [event["delivery_state"] for event in events] == ["needs_you"]

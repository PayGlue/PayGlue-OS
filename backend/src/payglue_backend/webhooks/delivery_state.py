# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""One answer to "did this purchase reach Ghost?" (PG-402).

Before this module the dashboard pill, the fourth stat card, the connection
health list, the activity feed, the events page, the connections overview, the
console overview, the System page and the customer file each read the raw
status on their own. The same Digistore24 delivery came out as "All systems
healthy", "0 / All delivered", "1 retrying" and a red "Delivery failed" on one
screen, and as "Nothing is waiting" next to "1 stuck" in the console. Every one
of them reads the state from here now, and the counts come from the same
predicate as the list behind the link, so a number and the rows it points to
cannot disagree.

The states, in the order they are decided:

- delivered: processed, access reached Ghost.
- skipped: deliberately not applied, with a reason. An event type PayGlue does
  not act on (Digistore24's on_rebill_cancelled and the other noted events), a
  duplicate delivery, a cancellation that runs to the end of the paid period.
- scheduled: the end of a paid period, queued by period_ends.schedule() as a
  received event with a future next_attempt_at. Planned work for the nightly
  end_paid_periods job, not a retry and not a problem, even on the day it is
  due and before the job has run.
- in_flight: received or being processed right now.
- retrying: failed, and the worker has a next attempt queued with attempts left.
- rejected: failed its signature or token check and nothing will retry it. A
  replay checks it again, and for providers that sign with a timestamp that
  check fails as stale, so it is not something the publisher can click away.
  The delivery alert mail still tells them when this keeps happening.
- test: a test-mode purchase that did not get through. Marked by the worker on
  the terminal failure (TEST_MARKER); events from before PG-402 carry no marker.
- needs_you: nothing will happen any more unless somebody acts. Dead letters,
  failures without a next attempt (a non-retryable error, a paused tenant, a
  queue that could not be reached) and retries that are overdue, because no
  sweeper picks those up.

Counts take every stored event, which the nightly purge keeps to 90 days.
There is no second, shorter window: the dashboard card counted seven days,
the console thirty and the events list all of them, and a stuck delivery
older than a week vanished from the card while the list still showed it. A
count and the list behind it now cover the same rows.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Case, CharField, Count, F, Max, Q, Value, When
from django.utils import timezone

from payglue_backend.webhooks.models import WebhookInboundEvent
from payglue_backend.webhooks.period_ends import SCHEDULED_END_OF

_S = WebhookInboundEvent.Status

DELIVERED = "delivered"
SKIPPED = "skipped"
SCHEDULED = "scheduled"
IN_FLIGHT = "in_flight"
RETRYING = "retrying"
REJECTED = "rejected"
TEST = "test"
NEEDS_YOU = "needs_you"

# The order classify() decides in. The queryset expression follows it too.
STATES = (DELIVERED, SKIPPED, SCHEDULED, IN_FLIGHT, RETRYING, REJECTED, TEST, NEEDS_YOU)

# Set in endpoint_metadata by the worker when a test-mode purchase fails for good.
TEST_MARKER = "test_purchase"

# The longest backoff is five minutes. A next attempt this far in the past was
# never picked up, and nothing else will pick it up.
RETRY_GRACE = timedelta(minutes=10)

# The words for each state, the same the dashboard uses (frontend
# lib/deliveryHealth.ts), so the console and the customer say one thing.
LABELS = {
    DELIVERED: "Synced",
    SKIPPED: "Skipped",
    SCHEDULED: "Scheduled",
    IN_FLIGHT: "Processing",
    RETRYING: "Retrying",
    REJECTED: "Rejected",
    TEST: "Test purchase",
    NEEDS_YOU: "Needs you",
}


def _metadata(event: WebhookInboundEvent) -> dict:
    return event.endpoint_metadata if isinstance(event.endpoint_metadata, dict) else {}


def classify(event: WebhookInboundEvent, now: datetime | None = None) -> str:
    """The delivery state of one event. See the module docstring."""
    now = now or timezone.now()
    status = event.status
    if status == _S.PROCESSED:
        return DELIVERED
    if status == _S.SKIPPED:
        return SKIPPED
    meta = _metadata(event)
    if status == _S.RECEIVED and SCHEDULED_END_OF in meta:
        return SCHEDULED
    if status in (_S.RECEIVED, _S.PROCESSING):
        return IN_FLIGHT
    if (
        status == _S.FAILED
        and event.next_attempt_at is not None
        and event.next_attempt_at > now - RETRY_GRACE
        and event.attempts < event.max_attempts
    ):
        return RETRYING
    if status == _S.FAILED and event.verification_failed:
        return REJECTED
    if meta.get(TEST_MARKER) is True:
        return TEST
    return NEEDS_YOU


def state_q(state: str, now: datetime | None = None) -> Q:
    """The same rule as classify(), as a filter. Each state excludes the ones
    decided before it, so the eight filters split any queryset without overlap."""
    now = now or timezone.now()
    scheduled = Q(status=_S.RECEIVED, endpoint_metadata__has_key=SCHEDULED_END_OF)
    retrying = Q(
        status=_S.FAILED,
        next_attempt_at__isnull=False,
        next_attempt_at__gt=now - RETRY_GRACE,
        attempts__lt=F("max_attempts"),
    )
    terminal = Q(status__in=[_S.FAILED, _S.DEAD_LETTER]) & ~retrying
    rejected = terminal & Q(status=_S.FAILED, verification_failed=True)
    # __contains, not a key lookup: a missing key must read as "not a test",
    # and a negated key lookup on a missing key is NULL, which drops the row.
    test = terminal & ~rejected & Q(endpoint_metadata__contains={TEST_MARKER: True})
    rules = {
        DELIVERED: Q(status=_S.PROCESSED),
        SKIPPED: Q(status=_S.SKIPPED),
        SCHEDULED: scheduled,
        IN_FLIGHT: Q(status__in=[_S.RECEIVED, _S.PROCESSING]) & ~scheduled,
        RETRYING: retrying,
        REJECTED: rejected,
        TEST: test,
        NEEDS_YOU: terminal & ~rejected & ~test,
    }
    return rules[state]


def state_expression(now: datetime | None = None) -> Case:
    """classify() for a whole queryset at once: .annotate(state=state_expression())."""
    now = now or timezone.now()
    return Case(
        *(When(state_q(state, now), then=Value(state)) for state in STATES),
        default=Value(NEEDS_YOU),
        output_field=CharField(),
    )


def stored(tenant_slug: str | None = None):
    """Every stored event, optionally for one tenant."""
    events = WebhookInboundEvent.objects.all()
    if tenant_slug is not None:
        events = events.filter(tenant_slug=tenant_slug)
    return events


def needs_you(now: datetime | None = None, tenant_slug: str | None = None):
    """The events a person has to look at."""
    now = now or timezone.now()
    return stored(tenant_slug).filter(state_q(NEEDS_YOU, now))


def needs_you_groups(now: datetime | None = None, tenant_slug: str | None = None) -> list[dict]:
    """needs_you, one row per tenant and provider, newest first. For a group of
    one, the attempts of that event, which is what the line under the count
    names ("Digistore24, 3 of 5 attempts, no retry scheduled")."""
    now = now or timezone.now()
    rows = (
        needs_you(now, tenant_slug)
        .values("tenant_slug", "provider")
        .annotate(count=Count("id"), latest=Max("created_at"))
        .order_by("-latest")
    )
    groups = []
    for row in rows:
        group = dict(row)
        group["attempts"] = None
        group["max_attempts"] = None
        group["event_id"] = None
        if row["count"] == 1:
            event = (
                needs_you(now, tenant_slug)
                .filter(tenant_slug=row["tenant_slug"], provider=row["provider"])
                .only("attempts", "max_attempts")
                .first()
            )
            if event is not None:
                group["attempts"] = event.attempts
                group["max_attempts"] = event.max_attempts
                group["event_id"] = event.pk
        groups.append(group)
    return groups


def summary(tenant_slug: str, now: datetime | None = None) -> dict:
    """What the dashboard, the connections overview and the sidebar show for
    one tenant: counts per state, the same per provider, and the needs_you
    detail for the line under the card."""
    now = now or timezone.now()
    rows = (
        stored(tenant_slug)
        .annotate(delivery_state=state_expression(now))
        .values("provider", "delivery_state")
        .annotate(count=Count("id"))
    )
    counts = dict.fromkeys(STATES, 0)
    providers: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(STATES, 0))
    for row in rows:
        counts[row["delivery_state"]] += row["count"]
        providers[row["provider"]][row["delivery_state"]] += row["count"]
    return {
        "counts": counts,
        "providers": dict(providers),
        "needs_you": [
            {
                "provider": group["provider"],
                "count": group["count"],
                "attempts": group["attempts"],
                "max_attempts": group["max_attempts"],
                "latest_at": group["latest"],
            }
            for group in needs_you_groups(now, tenant_slug)
        ],
    }

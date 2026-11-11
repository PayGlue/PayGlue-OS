# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Ending access when a cancelled subscription's paid period runs out.

Most providers send an event of their own on that day. PayPal does not: a
cancellation arrives the moment the subscriber cancels, and nothing follows.
Gumroad does send subscription_ended on that day, but a single lost delivery
would leave access open for good, so its cancellations queue an end as well,
keyed like subscription_ended so the two cannot both apply. For such a provider the
adapter skips the cancellation with
AccessRunsUntilError and hands over a delivery that ends access. It is stored
here as an ordinary inbound event, received but due only at the end of the
period, so it shows up in the event log and can be replayed like any other.
The nightly end_paid_periods job processes the ones that are due.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from payglue_backend.core.errors import AccessRunsUntilError
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks import wiring
from payglue_backend.webhooks.models import WebhookInboundEvent

logger = logging.getLogger(__name__)

# Marks a scheduled end in endpoint_metadata, with the id of the cancellation.
SCHEDULED_END_OF = "scheduled_end_of"


def schedule(event: WebhookInboundEvent, error: AccessRunsUntilError) -> WebhookInboundEvent | None:
    """Queue the end of access for `event`, once per cancellation."""
    if error.end_payload is None or not isinstance(error.ends_at, datetime):
        return None
    try:
        snapshot = json.loads(error.end_payload)
    except ValueError:
        snapshot = None
    with transaction.atomic():
        existing = WebhookInboundEvent.objects.filter(
            tenant_slug=event.tenant_slug,
            provider=event.provider,
            **{f"endpoint_metadata__{SCHEDULED_END_OF}": event.id},
        ).first()
        if existing is not None:
            return existing
        return WebhookInboundEvent.objects.create(
            tenant_slug=event.tenant_slug,
            provider=event.provider,
            status=WebhookInboundEvent.Status.RECEIVED,
            next_attempt_at=error.ends_at,
            payload_raw=error.end_payload,
            payload_snapshot=snapshot,
            headers_snapshot={},
            endpoint_path=event.endpoint_path,
            endpoint_metadata={SCHEDULED_END_OF: event.id},
        )


def due(now: datetime | None = None):
    """Scheduled ends whose day has come."""
    return WebhookInboundEvent.objects.filter(
        status=WebhookInboundEvent.Status.RECEIVED,
        next_attempt_at__lte=now or timezone.now(),
        endpoint_metadata__has_key=SCHEDULED_END_OF,
    ).order_by("next_attempt_at", "id")


def still_active(event: WebhookInboundEvent) -> bool:
    """True when the subscriber took the cancellation back in the meantime.

    Asked of the provider, because a resumed subscription is the one case in
    which ending access on the scheduled day would be wrong. An adapter that
    cannot tell answers False, and the end goes ahead.
    """
    adapter = wiring.get_payment_adapter(event.provider)
    check = getattr(adapter, "subscription_is_active", None)
    if check is None:
        return False
    return bool(check(TenantContext(tenant_slug=event.tenant_slug), bytes(event.payload_raw)))

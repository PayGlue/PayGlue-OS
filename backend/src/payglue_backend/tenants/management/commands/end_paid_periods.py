# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-368: end access when a cancelled subscription's paid period runs out.

Only for providers that send nothing on that day (PayPal). Their cancellation
was skipped and left a scheduled end behind, see webhooks/period_ends.py. This
job processes the ones that are due like any other delivery. A subscriber who
resumed in the meantime keeps access: the provider is asked first, and if it
cannot be reached the end waits for the next night rather than guessing.
"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from payglue_backend.webhooks import period_ends
from payglue_backend.webhooks.models import WebhookInboundEvent
from payglue_backend.webhooks.tasks import process_inbound_webhook_event

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "PG-368: end access for cancelled subscriptions whose paid period has run out."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List the due ends without processing them.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        ended = resumed = waiting = 0
        for event in period_ends.due():
            label = f"{event.tenant_slug}/{event.provider} #{event.id}"
            try:
                active = period_ends.still_active(event)
            except Exception as exc:  # noqa: BLE001 - try again tomorrow, never guess
                waiting += 1
                logger.warning("end_paid_periods: %s could not be checked: %s", label, exc)
                self.stdout.write(f"  {label}: provider not reachable, next night")
                continue
            if dry_run:
                self.stdout.write(f"  {label}: {'resumed, keeps access' if active else 'would end access'}")
                continue
            if active:
                resumed += 1
                WebhookInboundEvent.objects.filter(pk=event.pk).update(
                    status=WebhookInboundEvent.Status.SKIPPED,
                    last_error="subscription resumed before the paid period ended",
                    next_attempt_at=None,
                    updated_at=timezone.now(),
                )
                continue
            ended += 1
            process_inbound_webhook_event(event.id, ignore_timing=True, skip_verification=True)
        self.stdout.write(f"end_paid_periods: {ended} ended, {resumed} resumed, {waiting} waiting")

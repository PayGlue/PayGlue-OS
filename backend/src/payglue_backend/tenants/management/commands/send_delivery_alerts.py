# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-192: proactively email a creator when access delivery to their Ghost
site is repeatedly failing.

We already have the event log + replay + dead-letter, but nothing warns the
creator proactively when their Ghost delivery breaks (a rotated/expired Ghost
Admin API key, Ghost down, ...). It fails silently -- new purchases stop
unlocking -- until someone checks the event log or members complain.

Threshold (chosen with André): a tenant's Ghost delivery is "failing" when the
last 3 *terminal* delivery outcomes within the last 24h are all failed/
dead_letter. Terminal = processed (success) or failed/dead_letter (failure);
received/processing (in flight) and skipped (not for us) are ignored. A single
success among the latest 3 clears it, so a one-off retry blip never alerts.

Dedup (same idea as the lifecycle mails): the alert state lives on the Ghost
IntegrationConfig.metadata, and we email only on the healthy -> failing
transition. Recovery resets the state (no "recovered" email, no nagging).

Provider signature/token failures are rejected at ingestion and never become
failed WebhookInboundEvents, so the failed/dead_letter events counted here are
effectively the Ghost-delivery failures -- exactly the case the creator can act
on.

Run daily (Railway cron), like the other maintenance commands. Fails safe: a
per-tenant error is logged and skipped, never aborts the whole run.
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from payglue_backend.authn.lifecycle_emails import send_ghost_delivery_alert
from payglue_backend.tenants.models import TenantMembership
from payglue_backend.webhooks.models import IntegrationConfig, WebhookInboundEvent

logger = logging.getLogger(__name__)

FAIL_STREAK = 3
WINDOW_HOURS = 24

_Status = WebhookInboundEvent.Status
_TERMINAL = [_Status.PROCESSED, _Status.FAILED, _Status.DEAD_LETTER]
_FAILURE = {_Status.FAILED, _Status.DEAD_LETTER}


def is_ghost_delivery_failing(tenant_slug: str) -> bool:
    """True when the last FAIL_STREAK terminal delivery outcomes within
    WINDOW_HOURS are all failures. Fewer than FAIL_STREAK terminal events in
    the window is treated as healthy (not enough signal to alarm)."""
    since = timezone.now() - timedelta(hours=WINDOW_HOURS)
    recent = list(
        WebhookInboundEvent.objects.filter(
            tenant_slug=tenant_slug,
            created_at__gte=since,
            status__in=_TERMINAL,
        )
        .order_by("-created_at")
        .values_list("status", flat=True)[:FAIL_STREAK]
    )
    return len(recent) >= FAIL_STREAK and all(s in _FAILURE for s in recent)


def _owner_email(tenant_slug: str) -> str | None:
    membership = (
        TenantMembership.objects.filter(
            tenant__slug=tenant_slug, role=TenantMembership.Role.OWNER
        )
        .select_related("user_profile")
        .first()
    )
    return membership.user_profile.email if membership else None


class Command(BaseCommand):
    help = (
        "PG-192: email tenant owners when access delivery to their Ghost site "
        "is repeatedly failing (healthy -> failing transition only)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending or writing state.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        # Only tenants with an enabled Ghost (cms) connection can have delivery.
        configs = IntegrationConfig.objects.filter(provider_key="cms", enabled=True)
        alerted = recovered = 0

        for config in configs:
            slug = config.tenant_slug
            try:
                failing = is_ghost_delivery_failing(slug)
                metadata = config.metadata or {}
                prior = metadata.get("delivery_alert", {}).get("state", "healthy")

                if failing and prior != "failing":
                    owner = _owner_email(slug)
                    if not owner:
                        self.stdout.write(f"{slug}: failing but no owner email, skipping")
                        continue
                    self.stdout.write(f"{slug}: Ghost delivery failing -> alerting {owner}")
                    if not dry_run:
                        if send_ghost_delivery_alert(owner, slug):
                            metadata["delivery_alert"] = {
                                "state": "failing",
                                "notified_at": timezone.now().isoformat(),
                            }
                            config.metadata = metadata
                            config.save(update_fields=["metadata", "updated_at"])
                            alerted += 1

                elif not failing and prior == "failing":
                    self.stdout.write(f"{slug}: Ghost delivery recovered")
                    if not dry_run:
                        metadata["delivery_alert"] = {"state": "healthy"}
                        config.metadata = metadata
                        config.save(update_fields=["metadata", "updated_at"])
                        recovered += 1
            except Exception:
                logger.exception("send_delivery_alerts: failed for tenant %s", slug)

        self.stdout.write(
            f"Done. alerted={alerted} recovered={recovered} "
            f"checked={configs.count()}{' (dry-run)' if dry_run else ''}"
        )

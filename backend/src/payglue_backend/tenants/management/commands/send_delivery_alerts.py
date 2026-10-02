# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Nightly follow-up for delivery incidents (PG-192, PG-319, PG-326).

The creator is alerted by the worker, the moment a purchase ends in a terminal
failure (webhooks/delivery_alerts.py). This job does the three things that
need distance or a second process:

1. Retry. An incident the worker could not mail is PENDING, with the reason
   on the row. This job runs in the cron service, which has its own
   configuration, so a worker that cannot send mail does not leave the creator
   in the dark for longer than a night (PG-326).
2. Escalate, once, internally. A tenant that has been failing for
   ESCALATE_AFTER_HOURS without a single processed event is probably not going
   to fix it alone. The clock starts when the creator was told, or when the
   incident began if they never could be told. The operator gets one notice
   and can decide whether to ask how things are going. The creator is not
   copied.
3. Reset as a fallback. Recovery is normally recorded by the worker on the
   next processed event. If that write was missed, a processed event newer
   than the incident clears the state here, so the next incident mails again.

Fails safe: a per-tenant error is logged and skipped, never aborts the run.
"""

import logging
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from payglue_backend.authn.lifecycle_emails import send_delivery_escalation_notice
from payglue_backend.tenants.models import TenantMembership
from payglue_backend.webhooks.delivery_alerts import ESCALATE_AFTER_HOURS, retry_pending
from payglue_backend.webhooks.models import DeliveryAlert, WebhookInboundEvent

logger = logging.getLogger(__name__)

_State = DeliveryAlert.State


def _owner_email(tenant_slug: str) -> str | None:
    membership = (
        TenantMembership.objects.filter(
            tenant__slug=tenant_slug, role=TenantMembership.Role.OWNER
        )
        .select_related("user_profile")
        .first()
    )
    return membership.user_profile.email if membership else None


def _processed_since(tenant_slug: str, moment: datetime) -> bool:
    return WebhookInboundEvent.objects.filter(
        tenant_slug=tenant_slug,
        status=WebhookInboundEvent.Status.PROCESSED,
        created_at__gt=moment,
    ).exists()


class Command(BaseCommand):
    help = (
        "PG-319/PG-326: retry creator alerts the worker could not send, send one "
        f"internal notice per incident still failing after {ESCALATE_AFTER_HOURS}h, "
        "and reset incidents that recovered."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending or writing state.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()
        open_alerts = list(DeliveryAlert.objects.exclude(state=_State.HEALTHY))
        told = escalated = recovered = 0

        for alert in open_alerts:
            slug = alert.tenant_slug
            try:
                started = alert.first_failed_at or alert.notified_at or alert.created_at
                if _processed_since(slug, started):
                    self.stdout.write(f"{slug}: delivery recovered")
                    if not dry_run:
                        DeliveryAlert.objects.filter(pk=alert.pk).update(
                            state=_State.HEALTHY, updated_at=now
                        )
                    recovered += 1
                    continue

                if alert.state == _State.PENDING:
                    self.stdout.write(
                        f"{slug}: creator not told yet ({alert.last_send_error or 'no reason recorded'}) -> retrying"
                    )
                    if not dry_run and retry_pending(slug):
                        told += 1
                    alert.refresh_from_db()

                if alert.escalated_at:
                    continue
                clock = alert.notified_at or started
                if now - clock < timedelta(hours=ESCALATE_AFTER_HOURS):
                    continue

                owner = _owner_email(slug) or ""
                self.stdout.write(
                    f"{slug}: still failing after {ESCALATE_AFTER_HOURS}h -> internal notice"
                )
                if dry_run:
                    continue
                if send_delivery_escalation_notice(
                    tenant_slug=slug,
                    owner_email=owner,
                    state={
                        "provider": alert.provider,
                        "kind": alert.kind,
                        "count": alert.failure_count or "?",
                        "since": alert.failing_since or "?",
                        "notified_at": alert.notified_at.isoformat() if alert.notified_at else "",
                        "send_error": alert.last_send_error,
                    },
                ):
                    DeliveryAlert.objects.filter(pk=alert.pk).update(
                        escalated_at=now, updated_at=now
                    )
                    escalated += 1
            except Exception:
                logger.exception("send_delivery_alerts: failed for tenant %s", slug)

        pending = DeliveryAlert.objects.filter(state=_State.PENDING).count()
        self.stdout.write(
            f"Done. told={told} escalated={escalated} recovered={recovered} "
            f"pending={pending} checked={len(open_alerts)}{' (dry-run)' if dry_run else ''}"
        )

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Nightly follow-up for delivery incidents (PG-192, reshaped in PG-319).

The creator is no longer alerted from here. The worker mails them the moment
a purchase ends in a terminal failure (webhooks/delivery_alerts.py), because
the old rule, three failures inside 24 hours, was never met by a creator with
one sale a day. This job does the two things that need distance:

1. Escalate, once, internally. A tenant that was told about the failure
   ESCALATE_AFTER_HOURS ago and has not had a single processed event since is
   probably not going to fix it alone. The operator gets one notice and can
   decide whether to ask how things are going. The creator is not copied.
2. Reset as a fallback. Recovery is normally recorded by the worker on the
   next processed event. If that write was missed, a processed event newer
   than the alert clears the state here, so the next incident mails again.

Fails safe: a per-tenant error is logged and skipped, never aborts the run.
"""

import logging
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from payglue_backend.authn.lifecycle_emails import send_delivery_escalation_notice
from payglue_backend.tenants.models import TenantMembership
from payglue_backend.webhooks.delivery_alerts import ESCALATE_AFTER_HOURS
from payglue_backend.webhooks.models import IntegrationConfig, WebhookInboundEvent

logger = logging.getLogger(__name__)


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
        "PG-319: one internal notice per delivery incident that is still failing "
        f"{ESCALATE_AFTER_HOURS}h after the creator was told, plus a fallback reset."
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
        configs = IntegrationConfig.objects.filter(provider_key="cms", enabled=True)
        escalated = recovered = 0

        for config in configs:
            slug = config.tenant_slug
            try:
                metadata = config.metadata or {}
                state = metadata.get("delivery_alert") or {}
                if state.get("state") != "failing":
                    continue

                notified_at = parse_datetime(state.get("notified_at") or "")
                if notified_at is None:
                    # Written by the pre-PG-319 command, which never stored a
                    # time. Treat as "told just now" so it escalates in two days.
                    notified_at = now
                    state["notified_at"] = now.isoformat()
                    metadata["delivery_alert"] = state
                    if not dry_run:
                        config.metadata = metadata
                        config.save(update_fields=["metadata", "updated_at"])
                elif timezone.is_naive(notified_at):
                    notified_at = timezone.make_aware(notified_at)

                if _processed_since(slug, notified_at):
                    self.stdout.write(f"{slug}: delivery recovered")
                    if not dry_run:
                        metadata["delivery_alert"] = {"state": "healthy"}
                        config.metadata = metadata
                        config.save(update_fields=["metadata", "updated_at"])
                    recovered += 1
                    continue

                if state.get("escalated_at"):
                    continue
                if now - notified_at < timedelta(hours=ESCALATE_AFTER_HOURS):
                    continue

                owner = _owner_email(slug) or ""
                self.stdout.write(
                    f"{slug}: still failing {ESCALATE_AFTER_HOURS}h after the alert -> internal notice"
                )
                if dry_run:
                    continue
                if send_delivery_escalation_notice(
                    tenant_slug=slug, owner_email=owner, state=state
                ):
                    state["escalated_at"] = now.isoformat()
                    metadata["delivery_alert"] = state
                    config.metadata = metadata
                    config.save(update_fields=["metadata", "updated_at"])
                    escalated += 1
            except Exception:
                logger.exception("send_delivery_alerts: failed for tenant %s", slug)

        self.stdout.write(
            f"Done. escalated={escalated} recovered={recovered} "
            f"checked={configs.count()}{' (dry-run)' if dry_run else ''}"
        )

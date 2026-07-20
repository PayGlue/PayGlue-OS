# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-194 (GDPR): purge event/audit logs older than LOG_RETENTION_DAYS.

- WebhookInboundEvent holds the raw provider payload, which includes the
  end-customer's email (and whatever else the provider sends) -- that's PII
  we have no reason to keep indefinitely (GDPR Art. 5(1)(e) storage
  limitation). WebhookEventRecord is the idempotency log; a re-delivery
  after 90+ days is not a real scenario, so purging it in step is safe.
- PublicAuditEvent is the per-tenant audit trail shown on the dashboard's
  Events page. Same retention window, same notice.

The dashboard's Events page shows a matching "older than N days are
automatically deleted" notice, so the retention window and the copy must
stay in sync (both driven by settings.LOG_RETENTION_DAYS).

Meant to run on the same daily schedule as the other maintenance commands
(chained into the downgrade-enforcement-cron Railway service). Safe to run
often -- it only ever touches rows already past the window. --dry-run
reports counts without deleting.

Note: none of these tables are physically schema-separated (DJANGO_TENANTS
is off; they're one table each, tenant-scoped by a tenant_slug column), so a
single global delete covers every tenant.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from payglue_backend.tenants.models import PublicAuditEvent
from payglue_backend.webhooks.models import WebhookEventRecord, WebhookInboundEvent

# (label, model, timestamp field) -- WebhookEventRecord tracks its age on
# started_at, the other two on created_at.
_MODELS = (
    ("Webhook inbound events", WebhookInboundEvent, "created_at"),
    ("Webhook event records (idempotency)", WebhookEventRecord, "started_at"),
    ("Public audit events", PublicAuditEvent, "created_at"),
)


class Command(BaseCommand):
    help = "Delete webhook event and audit log rows older than LOG_RETENTION_DAYS (GDPR)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many rows would be deleted without deleting anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        retention_days = int(getattr(settings, "LOG_RETENTION_DAYS", 90))
        cutoff = timezone.now() - timedelta(days=retention_days)

        total = 0
        for label, model, ts_field in _MODELS:
            queryset = model.objects.filter(**{f"{ts_field}__lt": cutoff})
            count = queryset.count()
            total += count
            if count == 0:
                continue
            self.stdout.write(f"{label}: {count} rows older than {retention_days}d")
            if not dry_run:
                queryset.delete()

        # Data minimisation: the raw provider body (payload_raw) is only ever
        # read again while an event can still be (re)processed. A PROCESSED
        # event is terminal -- it is never reprocessed and never replayed
        # (TenantEventReplayView accepts only failed/dead_letter/skipped), so
        # its raw bytes are dead PII weight. Scrub them on a much shorter
        # window than the full-row purge above. payload_snapshot is left
        # intact so the dashboard's event detail still renders.
        payload_days = int(getattr(settings, "PAYLOAD_RAW_RETENTION_DAYS", 7))
        payload_cutoff = timezone.now() - timedelta(days=payload_days)
        redact_qs = WebhookInboundEvent.objects.filter(
            status=WebhookInboundEvent.Status.PROCESSED,
            created_at__lt=payload_cutoff,
        ).exclude(payload_raw=b"")
        redacted = redact_qs.count()
        if redacted:
            self.stdout.write(
                f"Raw payloads (processed, older than {payload_days}d): {redacted}"
            )
            if not dry_run:
                redact_qs.update(payload_raw=b"")

        if total == 0 and redacted == 0:
            self.stdout.write(f"Nothing to purge or scrub (retention {retention_days}d).")
        elif dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {total} rows would be deleted, {redacted} raw payloads scrubbed."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {total} expired log rows, scrubbed {redacted} raw payloads."
                )
            )

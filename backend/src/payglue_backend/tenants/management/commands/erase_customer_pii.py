# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-198 (GDPR Art. 17): erase one end-customer's PII from webhook event logs.

When a tenant receives a deletion request from one of *their* end-customers,
we must be able to remove that customer's personal data from our inbound
event logs *before* the 90-day auto-retention window (PG-194) would clear it.

The end-customer's email (and whatever else the provider sends) lives on
WebhookInboundEvent in three places: the raw payload bytes (payload_raw),
the parsed snapshot (payload_snapshot), and occasionally echoed into
last_error. We match rows by email and *scrub those fields in place* rather
than deleting the row -- deleting would break nothing functionally, but
keeping the (now PII-free) skeleton preserves the event count/audit trail
and leaves the idempotency chain (WebhookEventRecord, which stores no
payload) completely untouched, so a purged event can never be re-processed
by accident.

Matching is a case-insensitive substring search of the email against the
decoded payload bytes and the JSON snapshot. Emails are distinctive enough
that a substring match is reliable; scope with --tenant to bound the scan
and avoid touching another tenant's identically-addressed customer.

--dry-run reports how many rows would be scrubbed without changing anything.
"""
import json
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from payglue_backend.webhooks.models import WebhookInboundEvent

# Fields that may carry the end-customer's PII, and the empty value each is
# reset to. payload_raw is a BinaryField, the snapshots are JSON/text.
_SCRUB = {
    "payload_raw": b"",
    "payload_snapshot": None,
    "last_error": "",
}


def _row_matches(event: WebhookInboundEvent, needle: str) -> bool:
    """True if the (lowercased) email appears in this event's raw payload or
    parsed snapshot."""
    raw = bytes(event.payload_raw or b"").decode("utf-8", "ignore").lower()
    if needle in raw:
        return True
    if event.payload_snapshot is not None:
        if needle in json.dumps(event.payload_snapshot).lower():
            return True
    return False


class Command(BaseCommand):
    help = "Scrub one end-customer's PII (matched by email) from webhook event logs (GDPR Art. 17)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="End-customer email to erase.")
        parser.add_argument(
            "--tenant",
            default="",
            help="Restrict to a single tenant_slug (recommended to bound the scan).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many rows would be scrubbed without changing anything.",
        )

    def handle(self, *args, **options):
        email = (options["email"] or "").strip()
        if not email:
            raise CommandError("--email must not be empty.")
        needle = email.lower()
        tenant = (options["tenant"] or "").strip()
        dry_run = options["dry_run"]

        queryset = WebhookInboundEvent.objects.all()
        if tenant:
            queryset = queryset.filter(tenant_slug=tenant)

        matched = 0
        for event in queryset.iterator():
            if not _row_matches(event, needle):
                continue
            matched += 1
            if dry_run:
                continue
            for field, empty in _SCRUB.items():
                setattr(event, field, empty)
            meta = dict(event.endpoint_metadata or {})
            meta["pii_erased"] = True
            meta["pii_erased_at"] = timezone.now().isoformat()
            event.endpoint_metadata = meta
            event.save(update_fields=[*_SCRUB.keys(), "endpoint_metadata", "updated_at"])

        scope = f" for tenant '{tenant}'" if tenant else ""
        if matched == 0:
            self.stdout.write(f"No event rows contained '{email}'{scope}.")
        elif dry_run:
            self.stdout.write(
                self.style.WARNING(f"Dry run: {matched} rows contain '{email}'{scope} and would be scrubbed.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Scrubbed PII from {matched} event rows matching '{email}'{scope}.")
            )

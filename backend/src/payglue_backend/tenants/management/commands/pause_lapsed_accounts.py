# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-298: phase 3 of a lapsed subscription. Pauses every workspace of an
account whose 30-day grace period (BillingAccount.cancellation_detected_at,
set by send_lifecycle_emails) has run out without a new subscription.

Replaces delete_lapsed_accounts (PG-190), which deleted the account outright.
Deletion was the wrong ending: a customer whose card expired while on
holiday came back to nothing. Now the workspaces stop processing webhooks
and the dashboard shows only the plans page and the danger zone. Picking a
plan brings everything back; deleting is the customer's own call.

Accounts with needs_admin_review=True are excluded, the same second guard
delete_lapsed_accounts had: an unclear Creem status must never resolve
itself into a pause.

Meant to run on the same daily schedule as enforce_downgrade_grace_periods
and send_lifecycle_emails (all three chained in the same Railway cron
service's start command).
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from payglue_backend.authn.lifecycle_emails import send_lifecycle_email
from payglue_backend.tenants import lapse
from payglue_backend.tenants.models import BillingAccount, LifecycleEmailTemplate


class Command(BaseCommand):
    help = "Pause every workspace of accounts whose subscription grace period has expired."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report who would be paused without changing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=BillingAccount.GRACE_PERIOD_DAYS)
        due_accounts = BillingAccount.objects.filter(
            cancellation_detected_at__isnull=False,
            cancellation_detected_at__lte=cutoff,
            needs_admin_review=False,
            lapsed_at__isnull=True,
        ).select_related("owner", "plan")

        if not due_accounts:
            self.stdout.write("No accounts past their subscription grace period.")
            return

        for account in due_accounts:
            days_over = (timezone.now() - account.cancellation_detected_at).days - BillingAccount.GRACE_PERIOD_DAYS
            self.stdout.write(f"{account.owner.email}: grace period expired {days_over}d ago, pausing workspaces")
            if dry_run:
                continue
            paused = lapse.pause_account_tenants(account)
            self.stdout.write(f"  paused: {', '.join(t.slug for t in paused) or 'no active workspaces'}")
            send_lifecycle_email(account, LifecycleEmailTemplate.Trigger.ACCESS_PAUSED)

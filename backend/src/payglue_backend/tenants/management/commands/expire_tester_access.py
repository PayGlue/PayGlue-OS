# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-183: end tester access when a time-limited PayGlue license code's window
runs out.

Testers who redeemed a limited code (7/14/30 days) keep full access until
tester_access_expires_at. Once it passes, this starts the exact same 30-day
deletion grace as a real cancelled subscription (PG-190) by stamping
cancellation_detected_at -- which drives the dashboard grace banner (with the
plans/pricing nudge), and, if the tester never picks a real plan,
delete_lapsed_accounts removes the account once the grace period lapses.

"Never expires" testers have tester_access_expires_at = NULL and are never
selected here. Meant to run on the same daily cron as the other lifecycle
commands.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from payglue_backend.tenants.models import BillingAccount


class Command(BaseCommand):
    help = "Start the deletion grace period for testers whose access window has ended (PG-183)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report who would enter the grace period without changing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()
        due_accounts = BillingAccount.objects.filter(
            is_tester=True,
            tester_access_expires_at__isnull=False,
            tester_access_expires_at__lte=now,
            cancellation_detected_at__isnull=True,
        ).select_related("owner")

        if not due_accounts:
            self.stdout.write("No tester accounts past their access window.")
            return

        for account in due_accounts:
            self.stdout.write(
                f"{account.owner.email}: tester access ended, starting the "
                f"{BillingAccount.GRACE_PERIOD_DAYS}-day deletion grace period"
            )
            if dry_run:
                continue
            account.cancellation_detected_at = now
            account.save(update_fields=["cancellation_detected_at", "updated_at"])

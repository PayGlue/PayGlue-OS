# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-141: pauses tenants past the 1-month downgrade grace period.

A BillingAccount's downgrade_detected_at is set by CreemCheckoutWebhookView
when a customer moves to a lower-ranked plan (see authn/views.py). Once
that's more than 30 days in the past without an upgrade back (which clears
the field), the account's oldest tenants -- up to the new plan's
max_tenants -- stay active and the rest are paused. Paused tenants stop
processing inbound webhooks entirely (webhooks/tasks.py already gates on
tenant.status != ACTIVE, no separate change needed there).

Meant to run on a schedule (e.g. a Railway cron service, once per day) --
safe to run more often since it only acts on accounts whose grace period
has actually expired.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from payglue_backend.tenants.models import BillingAccount, Tenant

GRACE_PERIOD_DAYS = BillingAccount.GRACE_PERIOD_DAYS


class Command(BaseCommand):
    help = "Pause tenants for BillingAccounts whose downgrade grace period has expired."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=GRACE_PERIOD_DAYS)
        due_accounts = BillingAccount.objects.filter(
            downgrade_detected_at__isnull=False, downgrade_detected_at__lte=cutoff
        ).select_related("plan", "owner")

        if not due_accounts:
            self.stdout.write("No accounts past their downgrade grace period.")
            return

        for account in due_accounts:
            self._enforce_account(account, dry_run)

    def _enforce_account(self, account: BillingAccount, dry_run: bool) -> None:
        active_tenants = list(
            Tenant.objects.filter(
                billing_account=account, status=Tenant.Status.ACTIVE
            ).order_by("created_at")
        )
        limit = account.plan.max_tenants
        if limit is None or len(active_tenants) <= limit:
            # Unlimited plan, or already within the new limit (e.g. the
            # downgrade never actually put them over) -- nothing to pause,
            # just clear the flag so this account stops showing up here.
            if not dry_run:
                account.downgrade_detected_at = None
                account.save(update_fields=["downgrade_detected_at", "updated_at"])
            return

        to_pause = active_tenants[limit:]
        self.stdout.write(
            f"{account.owner.email} ({account.plan.key}, limit {limit}): "
            f"pausing {len(to_pause)} of {len(active_tenants)} active tenants "
            f"({', '.join(t.slug for t in to_pause)})"
        )
        if dry_run:
            return

        with transaction.atomic():
            # .update(), not .save() -- Tenant inherits django_tenants'
            # TenantMixin, whose save() re-checks/creates the Postgres
            # schema on every write. A plain status flip has no business
            # touching that; .update() goes straight to SQL and skips it.
            Tenant.objects.filter(pk__in=[t.pk for t in to_pause]).update(
                status=Tenant.Status.PAUSED, updated_at=timezone.now()
            )
            account.downgrade_detected_at = None
            account.save(update_fields=["downgrade_detected_at", "updated_at"])

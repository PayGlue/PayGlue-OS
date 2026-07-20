# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-190: permanently deletes accounts whose subscription was confirmed
canceled (BillingAccount.cancellation_detected_at, set by
send_lifecycle_emails) more than 30 days ago without resubscribing.

There is deliberately no "no active plan" state for an owner -- team
members never have their own BillingAccount, only owners do, so a lapsed
owner's account is either paying or on its way to full deletion, never a
permanent free tier. Reuses the exact same cascade (Supabase login first,
then sole-owned tenants + content, shared tenants keep only their
membership removed) already built and tested for PG-187's Django Admin
"delete user" flow -- see tenants/cascade_delete.py.

Accounts with needs_admin_review=True are always excluded, even if
cancellation_detected_at happens to be set -- an ambiguous Creem status
(past_due/unpaid/paused/fetch failure) must never resolve itself into an
automatic deletion; only a confirmed "canceled" status ever sets
cancellation_detected_at in the first place, but this filter is kept as a
second, defense-in-depth guard.

Meant to run on the same daily schedule as enforce_downgrade_grace_periods
and send_lifecycle_emails (all three chained in the same Railway cron
service's start command).
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from payglue_backend.tenants.cascade_delete import (
    clear_shared_tenant_billing_links,
    delete_tenant_cascade,
    sole_and_shared_tenants,
)
from payglue_backend.tenants.models import BillingAccount
from payglue_backend.tenants.supabase_admin import SupabaseAdminError, delete_supabase_user


class Command(BaseCommand):
    help = "Permanently delete BillingAccounts whose cancellation grace period has expired."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report who would be deleted without deleting anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=BillingAccount.GRACE_PERIOD_DAYS)
        due_accounts = BillingAccount.objects.filter(
            cancellation_detected_at__isnull=False,
            cancellation_detected_at__lte=cutoff,
            needs_admin_review=False,
        ).select_related("owner")

        if not due_accounts:
            self.stdout.write("No accounts past their cancellation grace period.")
            return

        for account in due_accounts:
            self._delete_account(account, dry_run)

    def _delete_account(self, account: BillingAccount, dry_run: bool) -> None:
        profile = account.owner
        days_overdue = (timezone.now() - account.cancellation_detected_at).days - BillingAccount.GRACE_PERIOD_DAYS
        self.stdout.write(f"{profile.email}: cancellation grace period expired {days_overdue}d ago, deleting")
        if dry_run:
            return

        # Supabase deletion first -- same ordering and same fail-safe as the
        # existing Django Admin "delete user" flow: if it fails, nothing
        # local gets touched, so a user is never left in a half-deleted
        # state that the (now possibly still-alive) Supabase login can't
        # match anymore.
        try:
            delete_supabase_user(profile.firebase_uid)
        except SupabaseAdminError as exc:
            self.stderr.write(f"{profile.email}: Supabase account deletion failed ({exc}), skipping this account")
            return

        sole_owner_tenants, shared_tenants = sole_and_shared_tenants(profile)
        with transaction.atomic():
            clear_shared_tenant_billing_links(profile, shared_tenants)
            for tenant in sole_owner_tenants:
                delete_tenant_cascade(tenant)
            profile.delete()

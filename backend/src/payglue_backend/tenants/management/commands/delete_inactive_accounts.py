# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-303: phase 4 of a lapsed subscription. Deletes accounts that have been
paused (BillingAccount.lapsed_at, set by pause_lapsed_accounts) for three
months without picking a plan.

The pause from PG-298 is deliberately reversible: sign in, pick a plan, and
everything is back. It is not meant to be permanent storage for somebody who
left. After DELETE_AFTER_PAUSED_DAYS the account goes the same way the
danger zone and the admin delete it (tenants/cascade_delete.py): Supabase
login first, then the workspaces this person solely owned with everything
in them, shared workspaces only lose the membership.

Three guards, all of them refuse rather than guess:

- needs_admin_review: an unclear provider status never ends in a deletion.
- last_known_subscription_status alive: the poll saw a subscription that is
  running. The poll itself clears lapsed_at in that case, so this is only a
  second line for a night where the poll failed and the pause job ran on.
- No deletion notice: the owner must have had the week's warning. A disabled
  notice template therefore stalls the deletion, visibly in the nightly log,
  instead of deleting somebody unwarned.

Supabase first, same order and same fail-safe as the original PG-190 job: if
the login cannot be removed nothing local is touched, so no half-deleted
account is left behind that a still-working login cannot reach.

Payment records are not part of this. They live at the payment provider,
who has to keep them for the statutory period; the receipt says so.
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from payglue_backend.authn.lifecycle_emails import (
    notify_admin_inactive_account_deleted,
    send_inactive_account_deleted_email,
)
from payglue_backend.tenants import lapse
from payglue_backend.tenants.cascade_delete import (
    clear_shared_tenant_billing_links,
    delete_tenant_cascade,
    sole_and_shared_tenants,
)
from payglue_backend.tenants.models import BillingAccount, LifecycleEmailLog, LifecycleEmailTemplate
from payglue_backend.tenants.supabase_admin import SupabaseAdminError, delete_supabase_user


class Command(BaseCommand):
    help = "Delete accounts that have been paused for three months without a new plan."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report who would be deleted without deleting anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        now = timezone.now()
        cutoff = now - timedelta(days=lapse.DELETE_AFTER_PAUSED_DAYS)
        due_accounts = (
            BillingAccount.objects.filter(
                lapsed_at__isnull=False, lapsed_at__lte=cutoff, needs_admin_review=False
            )
            .exclude(last_known_subscription_status__in=lapse.ALIVE_STATUSES)
            .select_related("owner", "plan")
        )

        if not due_accounts:
            self.stdout.write("No accounts paused long enough to delete.")
            return

        for account in due_accounts:
            self._delete_account(account, now, dry_run)

    def _notice_sent_in_time(self, account: BillingAccount, now: datetime) -> bool:
        """The deletion notice went out for this pause, and at least the
        promised number of days ago. A notice that went out late (template
        switched on late, a night the job did not run) pushes the deletion
        back by the same amount rather than shortening the warning."""
        latest = (
            LifecycleEmailLog.objects.filter(
                billing_account=account,
                trigger=LifecycleEmailTemplate.Trigger.DELETION_NOTICE,
                sent_at__gte=account.lapsed_at,
            )
            .order_by("-sent_at")
            .values_list("sent_at", flat=True)
            .first()
        )
        if latest is None:
            return False
        return now - latest >= timedelta(days=lapse.DELETION_NOTICE_DAYS_BEFORE)

    def _delete_account(self, account: BillingAccount, now: datetime, dry_run: bool) -> None:
        profile = account.owner
        email = profile.email
        plan_name = account.plan.name
        days_paused = (now - account.lapsed_at).days

        if not self._notice_sent_in_time(account, now):
            self.stdout.write(
                f"{email}: paused {days_paused}d, but the deletion notice has not been out for "
                f"{lapse.DELETION_NOTICE_DAYS_BEFORE}d, keeping the account"
            )
            return

        self.stdout.write(f"{email}: paused {days_paused}d, deleting")
        if dry_run:
            return

        try:
            delete_supabase_user(profile.firebase_uid)
        except SupabaseAdminError as exc:
            self.stderr.write(f"{email}: Supabase account deletion failed ({exc}), skipping this account")
            return

        sole_owner_tenants, shared_tenants = sole_and_shared_tenants(profile)
        with transaction.atomic():
            clear_shared_tenant_billing_links(profile, shared_tenants)
            for tenant in sole_owner_tenants:
                delete_tenant_cascade(tenant)
            profile.delete()

        self.stdout.write(
            f"  deleted: {', '.join(t.slug for t in sole_owner_tenants) or 'no solely owned workspaces'}"
            + (f"; left: {', '.join(t.slug for t in shared_tenants)}" if shared_tenants else "")
        )
        # Address and plan captured above: the rows they lived on are gone.
        send_inactive_account_deleted_email(email, plan_name)
        notify_admin_inactive_account_deleted(email, len(sole_owner_tenants), len(shared_tenants))

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-148: detects subscription-lifecycle transitions for PayGlue's own
paying customers by polling Creem, not by listening for a webhook.

There's no verified Creem subscription.updated/canceled webhook payload to
build on, and a customer cancelling via Creem's own customer portal never
sends us a webhook at all either way. Instead, this reuses
_creem_subscription_for_switch -- the same helper already live-verified
today for the Plans page and the Billing card -- to read each account's
*current* subscription state and diff it against what we saw last time
(BillingAccount.last_known_*):

- cancel_at_period_end flips false -> true on an active subscription: the
  owner scheduled a cancellation but still has access until period end.
  SCHEDULED_CANCELLATION fires here, not on the eventual real end, so
  there's still time to react to it.
- The lookup helper stops finding an active/trialing subscription at all
  for an account that previously had one. PG-190: this alone isn't enough
  to conclude "cancelled" -- past_due/unpaid/paused (a payment retry in
  progress) look identical from here. _creem_raw_subscription_status fetches
  the literal Creem status to tell them apart: only "canceled" starts the
  30-day deletion grace period (SUBSCRIPTION_ENDED fires as the day-1
  notice); anything else flags BillingAccount.needs_admin_review and alerts
  André instead of guessing -- he can check Creem directly. There's
  deliberately no "no active plan" state for an owner (team members never
  have their own BillingAccount), so a confirmed cancellation eventually
  means full account deletion (delete_lapsed_accounts), not a downgrade.

Meant to run on the same daily schedule as enforce_downgrade_grace_periods
and delete_lapsed_accounts (all three chained in the same Railway cron
service's start command) -- polling more often wouldn't catch anything
sooner than a day either way.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.utils import timezone

from payglue_backend.authn.lifecycle_emails import notify_admin_review_needed, send_lifecycle_email
from payglue_backend.tenants.models import BillingAccount, LifecycleEmailLog, LifecycleEmailTemplate


class Command(BaseCommand):
    help = "Poll Creem subscription state for PayGlue's own customers and send lifecycle emails on transitions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending or writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        # Only accounts that have ever actually had a subscription -- a
        # BillingAccount that's never been through a real Creem checkout
        # has nothing to poll for.
        accounts = BillingAccount.objects.exclude(creem_subscription_id="").select_related(
            "owner", "plan"
        )

        if not accounts:
            self.stdout.write("No billing accounts with a subscription on file.")
        else:
            for account in accounts:
                self._check_account(account, dry_run)

        self._send_cancellation_reminders(dry_run)
        self._send_day15_checkins(dry_run)

    def _check_account(self, account: BillingAccount, dry_run: bool) -> None:
        from payglue_backend.tenants.views import _creem_subscription_for_switch

        found = _creem_subscription_for_switch(account.owner)

        if found is None:
            self._handle_not_found(account, dry_run)
            return

        sub, _api_key, _base_url, _sandbox = found
        new_status = str(sub.get("status") or "")
        new_cancel_at_period_end = bool(sub.get("cancel_at_period_end"))

        newly_scheduled_cancellation = new_cancel_at_period_end and not account.last_known_cancel_at_period_end
        if newly_scheduled_cancellation:
            self.stdout.write(f"{account.owner.email}: cancellation scheduled")
            if not dry_run:
                send_lifecycle_email(account, LifecycleEmailTemplate.Trigger.SCHEDULED_CANCELLATION)

        if not dry_run:
            account.last_known_subscription_status = new_status
            account.last_known_cancel_at_period_end = new_cancel_at_period_end
            update_fields = ["last_known_subscription_status", "last_known_cancel_at_period_end", "updated_at"]
            # PG-190: subscription confirmed alive again -- self-heal any
            # earlier ambiguous-review or cancellation-grace state (e.g. a
            # failed card retry that later succeeded).
            if account.needs_admin_review or account.cancellation_detected_at is not None:
                account.needs_admin_review = False
                account.admin_review_reason = ""
                account.cancellation_detected_at = None
                update_fields += ["needs_admin_review", "admin_review_reason", "cancellation_detected_at"]
            account.save(update_fields=update_fields)

    def _handle_not_found(self, account: BillingAccount, dry_run: bool) -> None:
        had_active_before = account.last_known_subscription_status in {"active", "trialing"}
        if had_active_before:
            self._classify_ended_subscription(account, dry_run)

        if not dry_run:
            account.last_known_subscription_status = ""
            account.last_known_cancel_at_period_end = False
            account.save(
                update_fields=["last_known_subscription_status", "last_known_cancel_at_period_end", "updated_at"]
            )

    def _classify_ended_subscription(self, account: BillingAccount, dry_run: bool) -> None:
        """PG-190: account was active/trialing last poll, isn't anymore --
        fetch the literal Creem status before deciding what that means."""
        from payglue_backend.tenants.views import _creem_raw_subscription_status

        raw_status = _creem_raw_subscription_status(account)

        if raw_status == "canceled":
            self.stdout.write(f"{account.owner.email}: subscription canceled, starting deletion grace period")
            if not dry_run:
                if account.cancellation_detected_at is None:
                    account.cancellation_detected_at = timezone.now()
                account.needs_admin_review = False
                account.admin_review_reason = ""
                account.save(
                    update_fields=[
                        "cancellation_detected_at", "needs_admin_review", "admin_review_reason", "updated_at",
                    ]
                )
                send_lifecycle_email(account, LifecycleEmailTemplate.Trigger.SUBSCRIPTION_ENDED)
            return

        # past_due / unpaid / paused / unrecognized / fetch failed -- could
        # be a temporary payment retry, not a real cancellation. Only André
        # (checking Creem directly) can tell the difference, so nothing
        # automatic starts the deletion clock. Only notify on the
        # False -> True transition, not on every daily poll while unresolved.
        if account.needs_admin_review:
            return
        reason = raw_status or "fetch_failed"
        self.stdout.write(f"{account.owner.email}: needs admin review ({reason})")
        if not dry_run:
            account.needs_admin_review = True
            account.admin_review_reason = reason
            account.save(update_fields=["needs_admin_review", "admin_review_reason", "updated_at"])
            notify_admin_review_needed(account, reason)

    def _send_cancellation_reminders(self, dry_run: bool) -> None:
        """PG-190: day-15 and day-29 reminders during the 30-day deletion
        grace period. The day-1 notice is SUBSCRIPTION_ENDED itself, sent
        above the moment cancellation_detected_at is set -- no separate
        trigger needed for that one. Runs over every account with an open
        grace period each poll, independent of today's per-account check,
        since it's driven by elapsed days, not today's transition."""
        due_accounts = BillingAccount.objects.filter(
            cancellation_detected_at__isnull=False, needs_admin_review=False
        ).select_related("owner", "plan")

        for account in due_accounts:
            days = (timezone.now() - account.cancellation_detected_at).days
            if days >= BillingAccount.GRACE_PERIOD_DAYS - 1:
                self._send_reminder_once(account, LifecycleEmailTemplate.Trigger.CANCELLATION_FINAL_WARNING, dry_run)
            elif days >= 15:
                self._send_reminder_once(account, LifecycleEmailTemplate.Trigger.CANCELLATION_REMINDER_15D, dry_run)

    def _send_reminder_once(self, account: BillingAccount, trigger: str, dry_run: bool) -> None:
        if LifecycleEmailLog.objects.filter(billing_account=account, trigger=trigger).exists():
            return
        self.stdout.write(f"{account.owner.email}: sending {trigger}")
        if not dry_run:
            send_lifecycle_email(account, trigger)

    def _send_day15_checkins(self, dry_run: bool) -> None:
        """Second onboarding email, roughly two weeks in.

        Asks the state directly instead of waiting for an event: is this
        account 15 days old and still a customer? That is the whole condition,
        and it is why this lives here rather than in an email tool -- an
        external tool would need PayGlue to push it a cancellation signal,
        while this one is already polling for exactly that.

        Deliberately not restricted to accounts with a Creem subscription id:
        testers and comped accounts are onboarding too, and the question "are
        they still here on day 15" is just as meaningful for them.

        The partial unique constraint on LifecycleEmailLog is the real guard
        against a second send; the exclude() below only spares us the work.
        """
        cutoff = timezone.now() - timedelta(days=15)
        already_sent = LifecycleEmailLog.objects.filter(
            trigger=LifecycleEmailTemplate.Trigger.ONBOARDING_DAY15
        ).values("billing_account_id")

        due = (
            BillingAccount.objects.filter(created_at__lte=cutoff)
            .exclude(id__in=already_sent)
            # Somebody already on the way out does not need a "how's it
            # going" note. cancellation_detected_at is the confirmed-cancelled
            # marker that starts the 30-day deletion grace period.
            .filter(cancellation_detected_at__isnull=True)
            .select_related("owner", "plan")
        )

        for account in due:
            if dry_run:
                self.stdout.write(f"[dry-run] day-15 check-in -> {account.owner.email}")
                continue
            try:
                send_lifecycle_email(
                    account, LifecycleEmailTemplate.Trigger.ONBOARDING_DAY15
                )
            except IntegrityError:
                # Lost a race with a concurrent run; the constraint did its job.
                continue

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-148: detects subscription-lifecycle transitions for PayGlue's own
paying customers by polling Creem, not by listening for a webhook.

There's no verified Creem subscription.updated/canceled webhook payload to
build on, and a customer cancelling via Creem's own customer portal never
sends us a webhook at all either way. Instead this reads each account's
current subscription state and diffs it against what we saw last time
(BillingAccount.last_known_*).

PG-298 changed two things:

- Which accounts are polled. Until then only accounts with a stored
  creem_subscription_id were, and a first purchase never stored one, so no
  first-time buyer was ever watched (found live: a founding member whose
  card had been declined four times sat on full access with nothing
  happening). Now every account is looked at; the lookup falls back to the
  owner's email and stores the id it finds.
- What a failed payment does. It used to hand the account to a human and
  stop. Now it walks the three phases described in tenants/lapse.py:
  past_due tells the customer, an ended subscription starts the 30-day grace
  period, and pause_lapsed_accounts pauses the workspaces after it.

Unclear cases still go to a human: a stored id that Creem no longer answers
for, or a status outside the known sets. Nothing in here guesses.

Meant to run on the same daily schedule as enforce_downgrade_grace_periods
and pause_lapsed_accounts (all three chained in the same Railway cron
service's start command). Polling more often wouldn't catch anything sooner
than a day either way.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.utils import timezone

from payglue_backend.authn.lifecycle_emails import notify_admin_review_needed, send_lifecycle_email
from payglue_backend.tenants import lapse
from payglue_backend.tenants.models import BillingAccount, LifecycleEmailLog, LifecycleEmailTemplate

Trigger = LifecycleEmailTemplate.Trigger


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
        # Testers have no Creem subscription; expire_tester_access owns their
        # clock. Everyone else is a customer or somebody we provisioned by
        # hand, and for the latter the lookup simply finds nothing.
        accounts = BillingAccount.objects.filter(is_tester=False).select_related("owner", "plan")

        if not accounts:
            self.stdout.write("No billing accounts to poll.")
        else:
            for account in accounts:
                self._check_account(account, dry_run)

        self._send_payment_failed_reminders(dry_run)
        self._send_cancellation_reminders(dry_run)
        self._send_deletion_notices(dry_run)
        self._send_day15_checkins(dry_run)

    # ----------------------------------------------------------------- poll

    def _check_account(self, account: BillingAccount, dry_run: bool) -> None:
        found = lapse.latest_creem_subscription_for_account(account)
        had_alive_before = account.last_known_subscription_status in lapse.ALIVE_STATUSES
        in_a_phase = (
            account.payment_failed_detected_at is not None
            or account.cancellation_detected_at is not None
            or account.lapsed_at is not None
        )

        if found is None:
            if account.creem_subscription_id or had_alive_before:
                # We know there was a subscription and Creem no longer
                # answers for it. That is a fetch problem or a deleted
                # record, not a status, so a human looks.
                self._flag_for_review(account, "not_found", dry_run)
            return

        sub, *_rest = found
        status = str(sub.get("status") or "")
        cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
        sub_id, customer_id = lapse.subscription_ids(sub)

        update_fields = ["last_known_subscription_status", "last_known_cancel_at_period_end", "updated_at"]
        if sub_id and sub_id != account.creem_subscription_id:
            account.creem_subscription_id = sub_id
            update_fields.append("creem_subscription_id")
        if customer_id and customer_id != account.creem_customer_id:
            account.creem_customer_id = customer_id
            update_fields.append("creem_customer_id")

        if status in lapse.ALIVE_STATUSES:
            self._alive(account, cancel_at_period_end, update_fields, dry_run)
        elif status in lapse.RETRYING_STATUSES and self._retrying_too_long(account):
            # past_due for longer than any retry schedule takes: treat it as
            # ended, the customer had the two phase-1 mails and the time.
            self._ended(account, status, had_alive_before, True, update_fields, dry_run)
        elif status in lapse.RETRYING_STATUSES:
            self._retrying(account, update_fields, dry_run)
        elif status in lapse.ENDED_STATUSES:
            self._ended(account, status, had_alive_before, in_a_phase, update_fields, dry_run)
        else:
            # A status outside the three known sets. Record it, tell a human.
            self._flag_for_review(account, status or "unknown", dry_run)

        if not dry_run:
            account.last_known_subscription_status = status
            account.last_known_cancel_at_period_end = cancel_at_period_end
            account.save(update_fields=update_fields)

    def _alive(self, account: BillingAccount, cancel_at_period_end: bool, update_fields: list[str], dry_run: bool) -> None:
        newly_scheduled = cancel_at_period_end and not account.last_known_cancel_at_period_end
        if newly_scheduled:
            self.stdout.write(f"{account.owner.email}: cancellation scheduled")
            if not dry_run:
                send_lifecycle_email(account, Trigger.SCHEDULED_CANCELLATION)

        # Subscription confirmed alive: self-heal whatever phase the account
        # was in (a retried card that went through, a resubscription the
        # webhook missed) and bring paused workspaces back.
        was_lapsed = account.lapsed_at is not None
        if (
            account.payment_failed_detected_at is not None
            or account.cancellation_detected_at is not None
            or account.needs_admin_review
            or was_lapsed
        ):
            self.stdout.write(f"{account.owner.email}: subscription alive again, clearing lapse state")
            if not dry_run:
                account.payment_failed_detected_at = None
                account.cancellation_detected_at = None
                account.needs_admin_review = False
                account.admin_review_reason = ""
                update_fields += [
                    "payment_failed_detected_at",
                    "cancellation_detected_at",
                    "needs_admin_review",
                    "admin_review_reason",
                ]
                if was_lapsed:
                    lapse.resume_paused_tenants(account)

    @staticmethod
    def _retrying_too_long(account: BillingAccount) -> bool:
        started = account.payment_failed_detected_at
        if started is None:
            return False
        return timezone.now() - started >= timedelta(days=lapse.PAYMENT_FAILED_MAX_DAYS)

    def _retrying(self, account: BillingAccount, update_fields: list[str], dry_run: bool) -> None:
        """Phase 1. Creem is still retrying the card."""
        if account.cancellation_detected_at is not None or account.lapsed_at is not None:
            # Already further along; past_due after an ending would be odd,
            # and going backwards would restart mails the customer had.
            return
        if account.payment_failed_detected_at is not None:
            return
        self.stdout.write(f"{account.owner.email}: payment failed, Creem retrying (phase 1)")
        if not dry_run:
            account.payment_failed_detected_at = timezone.now()
            update_fields.append("payment_failed_detected_at")
            send_lifecycle_email(account, Trigger.PAYMENT_FAILED)

    def _ended(
        self,
        account: BillingAccount,
        status: str,
        had_alive_before: bool,
        in_a_phase: bool,
        update_fields: list[str],
        dry_run: bool,
    ) -> None:
        """Phase 2. Creem gave up, or the customer cancelled."""
        if account.cancellation_detected_at is not None or account.lapsed_at is not None:
            return
        if not (had_alive_before or in_a_phase):
            # Never seen alive by us: an old subscription of somebody who is
            # comped or provisioned by hand today. Recording the status is
            # enough; starting a grace period for it would be an invention.
            return
        self.stdout.write(f"{account.owner.email}: subscription {status}, starting 30-day grace period (phase 2)")
        if not dry_run:
            account.cancellation_detected_at = timezone.now()
            account.payment_failed_detected_at = None
            account.needs_admin_review = False
            account.admin_review_reason = ""
            update_fields += [
                "cancellation_detected_at",
                "payment_failed_detected_at",
                "needs_admin_review",
                "admin_review_reason",
            ]
            send_lifecycle_email(account, Trigger.SUBSCRIPTION_ENDED)

    def _flag_for_review(self, account: BillingAccount, reason: str, dry_run: bool) -> None:
        # Only notify on the False -> True transition, not on every daily
        # poll while unresolved.
        if account.needs_admin_review:
            return
        self.stdout.write(f"{account.owner.email}: needs admin review ({reason})")
        if not dry_run:
            account.needs_admin_review = True
            account.admin_review_reason = reason
            account.save(update_fields=["needs_admin_review", "admin_review_reason", "updated_at"])
            notify_admin_review_needed(account, reason)

    # ------------------------------------------------------------ reminders

    def _send_payment_failed_reminders(self, dry_run: bool) -> None:
        """Phase 1, second mail. Driven by elapsed days since the first one,
        and only while the account is still in phase 1: an account that has
        moved on to the grace period gets that sequence instead."""
        cutoff = timezone.now() - timedelta(days=lapse.PAYMENT_FAILED_REMINDER_AFTER_DAYS)
        due = BillingAccount.objects.filter(
            payment_failed_detected_at__isnull=False,
            payment_failed_detected_at__lte=cutoff,
            cancellation_detected_at__isnull=True,
            lapsed_at__isnull=True,
        ).select_related("owner", "plan")
        for account in due:
            self._send_reminder_once(account, Trigger.PAYMENT_FAILED_REMINDER, dry_run)

    def _send_cancellation_reminders(self, dry_run: bool) -> None:
        """PG-190: day-15 and day-29 reminders during the 30-day grace
        period. The day-1 notice is SUBSCRIPTION_ENDED itself, sent the
        moment cancellation_detected_at is set. Runs over every account with
        an open grace period each poll, independent of today's per-account
        check, since it's driven by elapsed days, not today's transition."""
        due_accounts = BillingAccount.objects.filter(
            cancellation_detected_at__isnull=False, needs_admin_review=False, lapsed_at__isnull=True
        ).select_related("owner", "plan")

        for account in due_accounts:
            days = (timezone.now() - account.cancellation_detected_at).days
            if days >= BillingAccount.GRACE_PERIOD_DAYS - 1:
                self._send_reminder_once(account, Trigger.CANCELLATION_FINAL_WARNING, dry_run)
            elif days >= 15:
                self._send_reminder_once(account, Trigger.CANCELLATION_REMINDER_15D, dry_run)

    def _send_deletion_notices(self, dry_run: bool) -> None:
        """PG-303, phase 4: a week before a paused account is deleted, the
        owner hears about it once. delete_inactive_accounts refuses to delete
        an account this notice never reached, so a disabled template stalls
        the deletion instead of skipping the warning."""
        cutoff = timezone.now() - timedelta(
            days=lapse.DELETE_AFTER_PAUSED_DAYS - lapse.DELETION_NOTICE_DAYS_BEFORE
        )
        due = BillingAccount.objects.filter(
            lapsed_at__isnull=False, lapsed_at__lte=cutoff, needs_admin_review=False
        ).select_related("owner", "plan")
        for account in due:
            deletion_date = account.lapsed_at + timedelta(days=lapse.DELETE_AFTER_PAUSED_DAYS)
            self._send_reminder_once(
                account,
                Trigger.DELETION_NOTICE,
                dry_run,
                since=account.lapsed_at,
                extra_context={"deletion_date": deletion_date.strftime("%-d %B %Y")},
            )

    def _send_reminder_once(
        self,
        account: BillingAccount,
        trigger: str,
        dry_run: bool,
        since=None,
        extra_context: dict[str, str] | None = None,
    ) -> None:
        # Once per phase, not once per account: a customer who lapses twice
        # in a year gets the sequence twice. The log is scanned from the
        # phase start so an older send does not silence the current one.
        if since is None:
            since = account.cancellation_detected_at or account.payment_failed_detected_at
        log = LifecycleEmailLog.objects.filter(billing_account=account, trigger=trigger)
        if since is not None:
            log = log.filter(sent_at__gte=since)
        if log.exists():
            return
        self.stdout.write(f"{account.owner.email}: sending {trigger}")
        if not dry_run:
            send_lifecycle_email(account, trigger, extra_context)

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
            # going" note. cancellation_detected_at is the confirmed-ended
            # marker that starts the 30-day grace period.
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

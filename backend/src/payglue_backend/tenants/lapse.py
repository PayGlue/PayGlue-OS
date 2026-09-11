# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-298: what happens to an account whose subscription stops paying.

Three phases, all driven by the daily poll in send_lifecycle_emails:

1. Creem reports past_due. Creem is still retrying the card, so the customer
   is told and nothing else changes. No clock runs.
2. Creem reports the subscription as ended (unpaid, canceled, paused,
   expired). The 30-day grace period starts, with the day-1 mail, the day-15
   reminder and the day-29 warning. Access stays complete for those 30 days.
3. The grace period ran out. pause_lapsed_accounts pauses every workspace
   and records lapsed_at. Nothing is deleted: the owner can still sign in,
   pick a plan to come back, or delete the account from the danger zone.
4. PG-303: the pause is not forever. A week before the end of it the owner
   gets a notice; once three months of pause have passed and that notice has
   gone out, delete_inactive_accounts removes the account the same way the
   danger zone does. Payment records stay with the payment provider.

A completed checkout (the webhook in authn/views.py) or a subscription the
poll sees alive again ends whichever phase the account is in.

The status sets below are Creem's SubscriptionStatus enum as verified for
PG-190, plus the values Creem's dashboard uses in its lists. Anything not in
one of the three sets is treated as unclear and handed to a human.
"""
from django.utils import timezone

from payglue_backend.tenants.models import BillingAccount, Tenant

ALIVE_STATUSES = frozenset({"active", "trialing", "scheduled_cancel"})
RETRYING_STATUSES = frozenset({"past_due"})
ENDED_STATUSES = frozenset({"unpaid", "canceled", "cancelled", "paused", "expired", "inactive"})

# Phase 1: the second mail goes out this many days after the first one, if
# the subscription is still past_due by then.
PAYMENT_FAILED_REMINDER_AFTER_DAYS = 3
# Phase 1 has an end even if the provider never reports one. Found live: a
# card declined four times over a week still showed past_due at Creem days
# later. Without a cap the account would sit in phase 1 with full access for
# as long as Creem keeps the status, which is not a decision anyone made.
PAYMENT_FAILED_MAX_DAYS = 14
# Phase 4: how long a paused account is kept before it is deleted, and how
# far ahead of that the owner is warned. Three months is long enough for a
# holiday, a hospital stay or a forgotten inbox; it is not a free tier.
DELETE_AFTER_PAUSED_DAYS = 90
DELETION_NOTICE_DAYS_BEFORE = 7


def pause_account_tenants(account: BillingAccount) -> list[Tenant]:
    """Phase 3. Pauses every active tenant of the account and stamps lapsed_at.
    Paused tenants stop processing inbound webhooks (webhooks/tasks.py gates
    on ACTIVE) and the dashboard bounces to the paused page. Returns the
    tenants that were paused, for the caller's log line."""
    tenants = list(
        Tenant.objects.filter(billing_account=account, status=Tenant.Status.ACTIVE).order_by("created_at")
    )
    # .update(), not .save(): same reason as enforce_downgrade_grace_periods,
    # a status flip must not run model-level side effects.
    Tenant.objects.filter(pk__in=[t.pk for t in tenants]).update(status=Tenant.Status.PAUSED)
    account.lapsed_at = timezone.now()
    account.save(update_fields=["lapsed_at", "updated_at"])
    return tenants


def resume_paused_tenants(account: BillingAccount) -> list[Tenant]:
    """The account pays again. Resumes paused tenants, oldest first, up to
    the plan's limit. Tenants beyond the limit stay paused, exactly as they
    would after a downgrade: the plan decides how many may run, not the
    reactivation. Clears lapsed_at as well, so a caller that only has the
    account can use this on its own."""
    paused = list(
        Tenant.objects.filter(billing_account=account, status=Tenant.Status.PAUSED).order_by("created_at")
    )
    limit = account.plan.max_tenants
    if limit is not None:
        already_active = Tenant.objects.filter(
            billing_account=account, status=Tenant.Status.ACTIVE
        ).count()
        paused = paused[: max(0, limit - already_active)]
    Tenant.objects.filter(pk__in=[t.pk for t in paused]).update(status=Tenant.Status.ACTIVE)
    if account.lapsed_at is not None:
        account.lapsed_at = None
        account.save(update_fields=["lapsed_at", "updated_at"])
    return paused


def latest_creem_subscription_for_account(account: BillingAccount) -> tuple[dict, str, str, bool] | None:
    """Finds the subscription that belongs to this account, whatever its
    status. By id when one is stored, otherwise by the owner's email through
    the customer search and, failing that, the transaction list.

    This is the lookup the daily poll and the backfill share. The older
    helpers in tenants/views only ever return active subscriptions, which is
    right for a plan switch and wrong here: an account whose card died is
    exactly the one whose subscription is no longer active.

    Returns (subscription, api_key, base_url, sandbox) or None when Creem
    knows nothing about this account. A lookup that fails on the way is
    indistinguishable from "nothing there" at this level; callers use the
    stored id and last known status to tell the two apart.
    """
    from django.conf import settings

    from payglue_backend.authn.creem_access import CREEM_API_BASE, CREEM_TEST_API_BASE
    from payglue_backend.tenants.views import (
        _creem_customer_slots,
        _creem_fetch_subscription_by_id,
        _creem_fetch_subscriptions,
        _creem_fetch_transactions,
    )

    if account.creem_subscription_id:
        for api_key, base_url, sandbox in (
            (settings.CREEM_API_KEY, CREEM_API_BASE, False),
            (settings.CREEM_SANDBOX_API_KEY, CREEM_TEST_API_BASE, True),
        ):
            if not api_key:
                continue
            sub = _creem_fetch_subscription_by_id(account.creem_subscription_id, api_key, base_url, sandbox)
            if sub:
                return sub, api_key, base_url, sandbox
        return None

    for customer_id, api_key, base_url, sandbox in _creem_customer_slots(account.owner.email):
        candidates = _creem_fetch_subscriptions(customer_id, api_key, base_url, sandbox)
        if not candidates:
            seen: set[str] = set()
            for txn in _creem_fetch_transactions(customer_id, api_key, base_url, sandbox):
                ref = txn.get("subscription")
                sub_id = ref.get("id") if isinstance(ref, dict) else ref
                if not sub_id or str(sub_id) in seen:
                    continue
                seen.add(str(sub_id))
                sub = _creem_fetch_subscription_by_id(str(sub_id), api_key, base_url, sandbox)
                if sub:
                    candidates.append(sub)
        if candidates:
            return _newest(candidates), api_key, base_url, sandbox
    return None


def _newest(subscriptions: list[dict]) -> dict:
    """An alive subscription wins over a dead one, then the most recently
    created. A customer who cancelled and later bought again has two rows
    at Creem, and the one that matters is the one still running."""

    def key(sub: dict) -> tuple[int, str]:
        alive = 1 if str(sub.get("status") or "") in ALIVE_STATUSES else 0
        return alive, str(sub.get("created_at") or "")

    return max(subscriptions, key=key)


def subscription_ids(sub: dict) -> tuple[str, str]:
    """(subscription id, customer id) off a Creem subscription object, both
    empty-string safe."""
    from payglue_backend.authn.creem_access import creem_reference_id

    return creem_reference_id(sub.get("id")), creem_reference_id(sub.get("customer"))

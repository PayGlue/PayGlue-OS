# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-141: the enforce_downgrade_grace_periods management command pauses
the excess tenants (beyond the new plan's max_tenants) once a downgrade's
grace period has expired, keeping the oldest tenants active. Accounts
still inside the grace period, or already back within their new limit,
are left untouched."""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.tenants.models import BillingAccount, Plan, Tenant, UserProfile


pytestmark = pytest.mark.django_db


def _billing_account(email: str, plan_key: str, downgrade_days_ago: int | None) -> BillingAccount:
    plan = Plan.objects.get(key=plan_key)
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    account = BillingAccount.objects.create(owner=owner, plan=plan)
    if downgrade_days_ago is not None:
        account.downgrade_detected_at = timezone.now() - timedelta(days=downgrade_days_ago)
        account.save(update_fields=["downgrade_detected_at"])
    return account


def _tenant(slug: str, billing_account: BillingAccount, days_old: int) -> Tenant:
    tenant = Tenant.objects.create(
        slug=slug, schema_name=slug.replace("-", "_"), billing_account=billing_account
    )
    Tenant.objects.filter(pk=tenant.pk).update(
        created_at=timezone.now() - timedelta(days=days_old)
    )
    tenant.refresh_from_db()
    return tenant


def test_pauses_excess_tenants_past_grace_period() -> None:
    account = _billing_account("expired@example.com", "solo", downgrade_days_ago=31)
    oldest = _tenant("expired-oldest", account, days_old=100)
    middle = _tenant("expired-middle", account, days_old=50)
    newest = _tenant("expired-newest", account, days_old=10)

    out = StringIO()
    call_command("enforce_downgrade_grace_periods", stdout=out)

    oldest.refresh_from_db()
    middle.refresh_from_db()
    newest.refresh_from_db()
    account.refresh_from_db()

    assert oldest.status == Tenant.Status.ACTIVE
    assert middle.status == Tenant.Status.PAUSED
    assert newest.status == Tenant.Status.PAUSED
    assert account.downgrade_detected_at is None


def test_leaves_accounts_still_within_grace_period_untouched() -> None:
    account = _billing_account("fresh@example.com", "solo", downgrade_days_ago=5)
    tenant_a = _tenant("fresh-a", account, days_old=100)
    tenant_b = _tenant("fresh-b", account, days_old=50)

    call_command("enforce_downgrade_grace_periods")

    tenant_a.refresh_from_db()
    tenant_b.refresh_from_db()
    account.refresh_from_db()

    assert tenant_a.status == Tenant.Status.ACTIVE
    assert tenant_b.status == Tenant.Status.ACTIVE
    assert account.downgrade_detected_at is not None


def test_dry_run_does_not_write_anything() -> None:
    account = _billing_account("dryrun@example.com", "solo", downgrade_days_ago=31)
    oldest = _tenant("dryrun-oldest", account, days_old=100)
    newest = _tenant("dryrun-newest", account, days_old=10)

    out = StringIO()
    call_command("enforce_downgrade_grace_periods", "--dry-run", stdout=out)

    oldest.refresh_from_db()
    newest.refresh_from_db()
    account.refresh_from_db()

    assert oldest.status == Tenant.Status.ACTIVE
    assert newest.status == Tenant.Status.ACTIVE
    assert account.downgrade_detected_at is not None
    assert "pausing 1 of 2" in out.getvalue()


def test_clears_flag_without_pausing_when_already_within_limit() -> None:
    """Grace period expired, but the customer already dropped below the
    new limit on their own (e.g. deleted a tenant themselves) -- nothing
    to pause, just clear the stale flag."""
    account = _billing_account("already-fine@example.com", "solo", downgrade_days_ago=31)
    only_tenant = _tenant("already-fine-only", account, days_old=10)

    call_command("enforce_downgrade_grace_periods")

    only_tenant.refresh_from_db()
    account.refresh_from_db()

    assert only_tenant.status == Tenant.Status.ACTIVE
    assert account.downgrade_detected_at is None


def test_unlimited_plan_is_never_enforced() -> None:
    account = _billing_account("agency@example.com", "agency", downgrade_days_ago=31)
    tenants = [_tenant(f"agency-{i}", account, days_old=100 - i) for i in range(5)]

    call_command("enforce_downgrade_grace_periods")

    for tenant in tenants:
        tenant.refresh_from_db()
        assert tenant.status == Tenant.Status.ACTIVE
    account.refresh_from_db()
    assert account.downgrade_detected_at is None


def test_paused_tenant_is_blocked_from_processing_webhooks() -> None:
    """Regression guard: webhooks/tasks.py's existing tenant-status gate
    already rejects anything but ACTIVE -- confirms PAUSED needs no new
    gating code of its own."""
    from payglue_backend.webhooks.tasks import _process_inbound_webhook_event
    from payglue_backend.webhooks.models import WebhookInboundEvent

    account = _billing_account("paused-webhook@example.com", "solo", downgrade_days_ago=None)
    tenant = _tenant("paused-webhook-tenant", account, days_old=10)
    Tenant.objects.filter(pk=tenant.pk).update(status=Tenant.Status.PAUSED)

    event = WebhookInboundEvent.objects.create(
        tenant_slug=tenant.slug,
        provider="creem",
        status=WebhookInboundEvent.Status.RECEIVED,
        payload_raw=b"{}",
        endpoint_path=f"/t/{tenant.slug}/webhooks/creem/token/",
    )

    _process_inbound_webhook_event(event.id, ignore_timing=True, skip_verification=True)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.FAILED
    assert event.last_error == "tenant is not active"

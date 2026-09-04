# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-298: pause_lapsed_accounts pauses every workspace of an account whose
confirmed subscription end is more than 30 days old. It replaced PG-190's
delete_lapsed_accounts, which deleted the account; that name now forwards
here. Nothing is deleted any more, and a new plan brings the workspaces
back (tenants/lapse.resume_paused_tenants)."""
from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.tenants import lapse
from payglue_backend.tenants.models import (
    BillingAccount,
    LifecycleEmailTemplate,
    Plan,
    Tenant,
    TenantMembership,
    UserProfile,
)


@pytest.fixture(autouse=True)
def _dashboard_address(settings):
    settings.PUBLIC_APP_BASE_URL = "https://dashboard.example.com"


pytestmark = pytest.mark.django_db


def _billing_account(email: str, plan_key: str = "solo", **kwargs) -> BillingAccount:
    plan = Plan.objects.get(key=plan_key)
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    return BillingAccount.objects.create(owner=owner, plan=plan, **kwargs)


def _tenant(account: BillingAccount, slug: str, status: str = Tenant.Status.ACTIVE) -> Tenant:
    tenant = Tenant.objects.create(
        slug=slug, schema_name=slug.replace("-", "_"), billing_account=account, status=status
    )
    TenantMembership.objects.create(tenant=tenant, user_profile=account.owner, role=TenantMembership.Role.OWNER)
    return tenant


def _due(**kwargs) -> BillingAccount:
    kwargs.setdefault("cancellation_detected_at", timezone.now() - timedelta(days=31))
    return _billing_account(kwargs.pop("email", "due@example.com"), **kwargs)


def test_dry_run_changes_nothing() -> None:
    account = _due()
    tenant = _tenant(account, "dry-tenant")

    call_command("pause_lapsed_accounts", "--dry-run")

    account.refresh_from_db()
    tenant.refresh_from_db()
    assert account.lapsed_at is None
    assert tenant.status == Tenant.Status.ACTIVE


def test_due_account_is_paused_not_deleted() -> None:
    LifecycleEmailTemplate.objects.filter(trigger="access_paused").update(enabled=True)
    account = _due()
    first = _tenant(account, "first-tenant")
    second = _tenant(account, "second-tenant")

    call_command("pause_lapsed_accounts")

    account.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()
    assert account.lapsed_at is not None
    assert UserProfile.objects.filter(pk=account.owner_id).exists()
    assert first.status == Tenant.Status.PAUSED
    assert second.status == Tenant.Status.PAUSED
    assert [m.to for m in mail.outbox] == [["due@example.com"]]


def test_paused_account_is_not_paused_twice() -> None:
    LifecycleEmailTemplate.objects.filter(trigger="access_paused").update(enabled=True)
    _due()

    call_command("pause_lapsed_accounts")
    call_command("pause_lapsed_accounts")

    assert len(mail.outbox) == 1


def test_needs_admin_review_excludes_account_even_if_due() -> None:
    account = _due(email="review@example.com", needs_admin_review=True, admin_review_reason="not_found")
    tenant = _tenant(account, "review-tenant")

    call_command("pause_lapsed_accounts")

    account.refresh_from_db()
    tenant.refresh_from_db()
    assert account.lapsed_at is None
    assert tenant.status == Tenant.Status.ACTIVE


def test_not_yet_due_account_is_untouched() -> None:
    account = _due(email="soon@example.com", cancellation_detected_at=timezone.now() - timedelta(days=29))
    tenant = _tenant(account, "soon-tenant")

    call_command("pause_lapsed_accounts")

    account.refresh_from_db()
    tenant.refresh_from_db()
    assert account.lapsed_at is None
    assert tenant.status == Tenant.Status.ACTIVE


def test_delete_lapsed_accounts_forwards_to_pause() -> None:
    account = _due(email="alias@example.com")
    tenant = _tenant(account, "alias-tenant")

    call_command("delete_lapsed_accounts")

    account.refresh_from_db()
    tenant.refresh_from_db()
    assert UserProfile.objects.filter(pk=account.owner_id).exists()
    assert tenant.status == Tenant.Status.PAUSED


def test_no_due_accounts_writes_status_message(capsys) -> None:
    call_command("pause_lapsed_accounts")

    assert "No accounts past their subscription grace period." in capsys.readouterr().out


# ------------------------------------------------------ coming back


def test_resume_brings_tenants_back_within_plan_limit() -> None:
    """Solo allows one publication. A lapsed Solo account with two paused
    workspaces gets the older one back; the other stays paused, exactly as
    after a downgrade."""
    account = _billing_account("resume@example.com", "solo", lapsed_at=timezone.now())
    older = _tenant(account, "older-tenant", Tenant.Status.PAUSED)
    newer = _tenant(account, "newer-tenant", Tenant.Status.PAUSED)
    Tenant.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=100))

    resumed = lapse.resume_paused_tenants(account)

    account.refresh_from_db()
    older.refresh_from_db()
    newer.refresh_from_db()
    assert [t.slug for t in resumed] == ["older-tenant"]
    assert account.lapsed_at is None
    assert older.status == Tenant.Status.ACTIVE
    assert newer.status == Tenant.Status.PAUSED


def test_resume_on_unlimited_plan_brings_everything_back() -> None:
    account = _billing_account("founding@example.com", "founding", lapsed_at=timezone.now())
    a = _tenant(account, "a-tenant", Tenant.Status.PAUSED)
    b = _tenant(account, "b-tenant", Tenant.Status.PAUSED)

    lapse.resume_paused_tenants(account)

    a.refresh_from_db()
    b.refresh_from_db()
    assert a.status == Tenant.Status.ACTIVE
    assert b.status == Tenant.Status.ACTIVE

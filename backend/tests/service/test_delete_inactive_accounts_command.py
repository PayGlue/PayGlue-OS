# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-303: delete_inactive_accounts removes an account that has been paused
for three months, but only after the deletion notice has been out for a
week. Same cascade as the danger zone: solely owned workspaces go with
everything in them, shared ones keep running without this member."""
from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.tenants import lapse
from payglue_backend.tenants.models import (
    BillingAccount,
    LifecycleEmailLog,
    LifecycleEmailTemplate,
    Plan,
    Tenant,
    TenantMembership,
    UserProfile,
)
from payglue_backend.tenants.supabase_admin import SupabaseAdminError
from payglue_backend.webhooks.models import PaywallConfig

COMMAND = "payglue_backend.tenants.management.commands.delete_inactive_accounts"


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.PUBLIC_APP_BASE_URL = "https://dashboard.example.com"
    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"


@pytest.fixture(autouse=True)
def _no_supabase(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(f"{COMMAND}.delete_supabase_user", lambda uid: None)


pytestmark = pytest.mark.django_db


def _billing_account(email: str, plan_key: str = "solo", **kwargs) -> BillingAccount:
    plan = Plan.objects.get(key=plan_key)
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    return BillingAccount.objects.create(owner=owner, plan=plan, **kwargs)


def _tenant(account: BillingAccount, slug: str, status: str = Tenant.Status.PAUSED) -> Tenant:
    tenant = Tenant.objects.create(
        slug=slug, schema_name=slug.replace("-", "_"), billing_account=account, status=status
    )
    TenantMembership.objects.create(tenant=tenant, user_profile=account.owner, role=TenantMembership.Role.OWNER)
    return tenant


def _noticed(account: BillingAccount, days_ago: int = lapse.DELETION_NOTICE_DAYS_BEFORE) -> None:
    log = LifecycleEmailLog.objects.create(
        billing_account=account, trigger=LifecycleEmailTemplate.Trigger.DELETION_NOTICE
    )
    LifecycleEmailLog.objects.filter(pk=log.pk).update(sent_at=timezone.now() - timedelta(days=days_ago))


def _due(notice: bool = True, **kwargs) -> BillingAccount:
    kwargs.setdefault("lapsed_at", timezone.now() - timedelta(days=lapse.DELETE_AFTER_PAUSED_DAYS + 1))
    kwargs.setdefault("last_known_subscription_status", "canceled")
    account = _billing_account(kwargs.pop("email", "gone@example.com"), **kwargs)
    if notice:
        _noticed(account)
    return account


def test_due_account_is_deleted_with_its_workspaces_and_mailed() -> None:
    LifecycleEmailTemplate.objects.filter(trigger="inactive_account_deleted").update(enabled=True)
    account = _due()
    owner_id = account.owner_id
    tenant = _tenant(account, "gone-tenant")
    PaywallConfig.objects.create(id="pw_gone", tenant_slug=tenant.slug, name="members only")

    call_command("delete_inactive_accounts")

    assert not UserProfile.objects.filter(pk=owner_id).exists()
    assert not Tenant.objects.filter(pk=tenant.pk).exists()
    assert not PaywallConfig.objects.filter(tenant_slug="gone-tenant").exists()
    assert sorted(m.to[0] for m in mail.outbox) == ["gone@example.com", "ops@example.com"]
    receipt = next(m for m in mail.outbox if m.to == ["gone@example.com"])
    assert "Your PayGlue account has been deleted" in receipt.subject
    assert "payment provider" in receipt.body


def test_shared_workspace_survives_and_only_loses_the_member() -> None:
    account = _due(email="co-owner@example.com")
    other = _billing_account("other@example.com")
    shared = _tenant(other, "shared-tenant", Tenant.Status.ACTIVE)
    TenantMembership.objects.create(
        tenant=shared, user_profile=account.owner, role=TenantMembership.Role.OWNER
    )

    call_command("delete_inactive_accounts")

    shared.refresh_from_db()
    assert shared.status == Tenant.Status.ACTIVE
    assert not UserProfile.objects.filter(email="co-owner@example.com").exists()
    assert TenantMembership.objects.filter(tenant=shared).count() == 1


def test_dry_run_deletes_nothing(capsys) -> None:
    account = _due()
    tenant = _tenant(account, "dry-tenant")

    call_command("delete_inactive_accounts", "--dry-run")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()
    assert Tenant.objects.filter(pk=tenant.pk).exists()
    assert "deleting" in capsys.readouterr().out
    assert mail.outbox == []


def test_without_the_notice_the_account_is_kept(capsys) -> None:
    account = _due(notice=False)

    call_command("delete_inactive_accounts")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()
    assert "deletion notice has not been out" in capsys.readouterr().out


def test_a_late_notice_pushes_the_deletion_back() -> None:
    """Notice went out three days ago: the owner was promised a week."""
    account = _due(notice=False)
    _noticed(account, days_ago=3)

    call_command("delete_inactive_accounts")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()


def test_notice_from_an_earlier_pause_does_not_count() -> None:
    account = _due(notice=False)
    _noticed(account, days_ago=lapse.DELETE_AFTER_PAUSED_DAYS + 30)

    call_command("delete_inactive_accounts")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()


def test_not_paused_long_enough_is_untouched() -> None:
    account = _due(
        email="recent@example.com",
        lapsed_at=timezone.now() - timedelta(days=lapse.DELETE_AFTER_PAUSED_DAYS - 1),
    )

    call_command("delete_inactive_accounts")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()


def test_needs_admin_review_is_never_deleted() -> None:
    account = _due(email="review@example.com", needs_admin_review=True, admin_review_reason="not_found")

    call_command("delete_inactive_accounts")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()


def test_subscription_seen_alive_is_never_deleted() -> None:
    account = _due(email="alive@example.com", last_known_subscription_status="active")

    call_command("delete_inactive_accounts")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()


def test_supabase_failure_deletes_nothing_locally(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def boom(uid):
        raise SupabaseAdminError("503")

    monkeypatch.setattr(f"{COMMAND}.delete_supabase_user", boom)
    account = _due(email="stuck@example.com")
    tenant = _tenant(account, "stuck-tenant")

    call_command("delete_inactive_accounts")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()
    assert Tenant.objects.filter(pk=tenant.pk).exists()
    assert "Supabase account deletion failed" in capsys.readouterr().err
    assert mail.outbox == []


def test_no_due_accounts_writes_status_message(capsys) -> None:
    call_command("delete_inactive_accounts")

    assert "No accounts paused long enough to delete." in capsys.readouterr().out

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-190: delete_lapsed_accounts permanently deletes a BillingAccount's
owner once their confirmed cancellation is more than 30 days old, reusing
the exact same cascade as PG-187's Django Admin "delete user" flow --
Supabase login first, then sole-owned tenants + content, shared tenants
keep only their membership removed."""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.tenants.models import BillingAccount, Plan, Tenant, TenantMembership, UserProfile
from payglue_backend.tenants.supabase_admin import SupabaseAdminError
from payglue_backend.webhooks.models import PaywallConfig


pytestmark = pytest.mark.django_db

SUPABASE_PATCH_TARGET = "payglue_backend.tenants.management.commands.delete_lapsed_accounts.delete_supabase_user"


def _billing_account(email: str, **kwargs) -> BillingAccount:
    plan = Plan.objects.get(key="solo")
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    return BillingAccount.objects.create(owner=owner, plan=plan, **kwargs)


def _membership(profile: UserProfile, tenant: Tenant, role=TenantMembership.Role.OWNER) -> TenantMembership:
    return TenantMembership.objects.create(tenant=tenant, user_profile=profile, role=role)


def test_dry_run_deletes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "dryrun@example.com", cancellation_detected_at=timezone.now() - timedelta(days=35)
    )
    called = []
    monkeypatch.setattr(SUPABASE_PATCH_TARGET, lambda uid: called.append(uid))

    call_command("delete_lapsed_accounts", "--dry-run")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()
    assert called == []


def test_due_sole_owner_account_is_fully_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "sole-owner@example.com", cancellation_detected_at=timezone.now() - timedelta(days=31)
    )
    profile = account.owner
    tenant = Tenant.objects.create(
        slug="lapsed-sole-tenant", schema_name="lapsed_sole_tenant", billing_account=account
    )
    _membership(profile, tenant)
    PaywallConfig.objects.create(id="pw_lapsed", tenant_slug=tenant.slug, name="Lapsed Paywall")

    called = []
    monkeypatch.setattr(SUPABASE_PATCH_TARGET, lambda uid: called.append(uid))

    call_command("delete_lapsed_accounts")

    assert called == [profile.firebase_uid]
    assert not UserProfile.objects.filter(pk=profile.pk).exists()
    assert not BillingAccount.objects.filter(pk=account.pk).exists()
    assert not Tenant.objects.filter(pk=tenant.pk).exists()
    assert not PaywallConfig.objects.filter(tenant_slug=tenant.slug).exists()


def test_shared_tenant_survives_only_membership_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    account_a = _billing_account(
        "lapsed-shared-a@example.com", cancellation_detected_at=timezone.now() - timedelta(days=31)
    )
    profile_a = account_a.owner
    profile_b = UserProfile.objects.create(firebase_uid="uid-shared-b", email="shared-b@example.com")
    tenant = Tenant.objects.create(
        slug="lapsed-shared-tenant", schema_name="lapsed_shared_tenant", billing_account=account_a
    )
    _membership(profile_a, tenant)
    _membership(profile_b, tenant)

    monkeypatch.setattr(SUPABASE_PATCH_TARGET, lambda uid: None)

    call_command("delete_lapsed_accounts")

    assert not UserProfile.objects.filter(pk=profile_a.pk).exists()
    tenant.refresh_from_db()
    assert Tenant.objects.filter(pk=tenant.pk).exists()
    assert not TenantMembership.objects.filter(user_profile_id=profile_a.pk).exists()
    assert TenantMembership.objects.filter(user_profile=profile_b, tenant=tenant).exists()
    # The tenant still pointed at profile_a's own (now-deleted) BillingAccount
    # via a PROTECT FK -- must be cleared, not left dangling or crashing.
    assert tenant.billing_account_id is None


def test_needs_admin_review_excludes_account_even_if_cancellation_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "under-review@example.com",
        cancellation_detected_at=timezone.now() - timedelta(days=40),
        needs_admin_review=True,
    )
    called = []
    monkeypatch.setattr(SUPABASE_PATCH_TARGET, lambda uid: called.append(uid))

    call_command("delete_lapsed_accounts")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()
    assert called == []


def test_not_yet_due_account_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "still-in-grace@example.com", cancellation_detected_at=timezone.now() - timedelta(days=10)
    )
    called = []
    monkeypatch.setattr(SUPABASE_PATCH_TARGET, lambda uid: called.append(uid))

    call_command("delete_lapsed_accounts")

    assert UserProfile.objects.filter(pk=account.owner_id).exists()
    assert called == []


def test_supabase_deletion_failure_leaves_local_data_intact(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "supabase-fails@example.com", cancellation_detected_at=timezone.now() - timedelta(days=31)
    )
    profile = account.owner
    tenant = Tenant.objects.create(
        slug="lapsed-supabase-fail", schema_name="lapsed_supabase_fail", billing_account=account
    )
    _membership(profile, tenant)

    def _raise(_uid: str) -> None:
        raise SupabaseAdminError("boom")

    monkeypatch.setattr(SUPABASE_PATCH_TARGET, _raise)

    call_command("delete_lapsed_accounts")

    assert UserProfile.objects.filter(pk=profile.pk).exists()
    assert Tenant.objects.filter(pk=tenant.pk).exists()
    assert BillingAccount.objects.filter(pk=account.pk).exists()


def test_no_due_accounts_writes_status_message() -> None:
    call_command("delete_lapsed_accounts")

from unittest import mock

import pytest

from payglue_backend.core.errors import PlanLimitExceededError
from payglue_backend.tenants import plan_limits
from payglue_backend.tenants.models import BillingAccount, Plan, Tenant, TenantMembership, UserProfile


pytestmark = pytest.mark.django_db


def _solo_tenant(slug: str) -> Tenant:
    solo = Plan.objects.get(key="solo")
    owner = UserProfile.objects.create(firebase_uid=f"uid-{slug}", email=f"{slug}@example.com")
    billing_account = BillingAccount.objects.create(owner=owner, plan=solo)
    return Tenant.objects.create(
        slug=slug, schema_name=slug.replace("-", "_"), billing_account=billing_account
    )


def test_check_resource_limit_passes_under_limit() -> None:
    # Solo allows 1 team member; no membership rows yet, so 0/1.
    tenant = _solo_tenant("unit-under")
    plan_limits.check_resource_limit(tenant, "team members")  # does not raise


def test_check_resource_limit_raises_at_limit() -> None:
    tenant = _solo_tenant("unit-at-limit")
    TenantMembership.objects.create(
        tenant=tenant, user_profile=tenant.billing_account.owner, role=TenantMembership.Role.OWNER
    )
    with pytest.raises(PlanLimitExceededError) as exc_info:
        plan_limits.check_resource_limit(tenant, "team members")
    assert exc_info.value.resource == "team members"
    assert exc_info.value.limit == 1


def test_check_resource_limit_null_limit_never_raises() -> None:
    tenant = _solo_tenant("unit-unlimited")
    tenant.billing_account.plan = Plan.objects.get(key="agency")
    tenant.billing_account.save()
    for _ in range(5):
        TenantMembership.objects.create(
            tenant=tenant,
            user_profile=UserProfile.objects.create(
                firebase_uid=f"uid-extra-{_}", email=f"extra-{_}@example.com"
            ),
            role=TenantMembership.Role.ADMIN,
        )
    plan_limits.check_resource_limit(tenant, "team members")  # does not raise


def test_check_resource_limit_no_billing_account_is_exempt() -> None:
    tenant = _solo_tenant("unit-no-account")
    tenant.billing_account = None  # in-memory only, never persisted
    plan_limits.check_resource_limit(tenant, "team members")  # does not raise


def test_check_new_tenant_limit_none_account_is_noop() -> None:
    plan_limits.check_new_tenant_limit(None)  # does not raise


def test_check_new_tenant_limit_raises_at_max_tenants() -> None:
    tenant = _solo_tenant("unit-tenant-limit")
    with pytest.raises(PlanLimitExceededError) as exc_info:
        plan_limits.check_new_tenant_limit(tenant.billing_account)
    assert exc_info.value.resource == "publications"


def test_check_resource_limit_webhooks_model_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    """buy buttons/paywalls/pricing tables/providers live in the webhooks
    app, whose migrations need Postgres -- mock the model lookup so this
    unit test can run against any backend."""
    tenant = _solo_tenant("unit-buybutton")

    class _FakeQuerySet:
        def __init__(self, count: int) -> None:
            self._count = count

        def filter(self, **kwargs: object) -> "_FakeQuerySet":
            return self

        def count(self) -> int:
            return self._count

    class _FakeBuyButton:
        objects = _FakeQuerySet(0)

    with mock.patch("payglue_backend.webhooks.models.BuyButton", _FakeBuyButton):
        plan_limits.check_resource_limit(tenant, "buy buttons")  # 0/1, does not raise
        _FakeBuyButton.objects = _FakeQuerySet(1)
        with pytest.raises(PlanLimitExceededError):
            plan_limits.check_resource_limit(tenant, "buy buttons")  # 1/1, raises

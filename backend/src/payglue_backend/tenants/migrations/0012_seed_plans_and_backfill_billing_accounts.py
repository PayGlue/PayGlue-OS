# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations


PLAN_SEED = [
    {
        "key": "solo",
        "name": "Solo",
        "max_tenants": 1,
        "max_buy_buttons_per_tenant": 1,
        "max_paywalls_per_tenant": 1,
        "max_pricing_tables_per_tenant": 1,
        "max_providers_per_tenant": 2,
        "max_team_members_per_tenant": 1,
    },
    {
        "key": "studio",
        "name": "Studio",
        "max_tenants": 3,
        "max_buy_buttons_per_tenant": 5,
        "max_paywalls_per_tenant": 3,
        "max_pricing_tables_per_tenant": 3,
        "max_providers_per_tenant": 4,
        "max_team_members_per_tenant": 3,
    },
    {
        "key": "agency",
        "name": "Agency",
        "max_tenants": None,
        "max_buy_buttons_per_tenant": None,
        "max_paywalls_per_tenant": None,
        "max_pricing_tables_per_tenant": None,
        "max_providers_per_tenant": None,
        "max_team_members_per_tenant": None,
    },
    {
        "key": "founding",
        "name": "Founding Member",
        "max_tenants": None,
        "max_buy_buttons_per_tenant": None,
        "max_paywalls_per_tenant": None,
        "max_pricing_tables_per_tenant": None,
        "max_providers_per_tenant": None,
        "max_team_members_per_tenant": None,
    },
]


def seed_plans_and_backfill(apps, schema_editor):
    Plan = apps.get_model("tenants", "Plan")
    BillingAccount = apps.get_model("tenants", "BillingAccount")
    Tenant = apps.get_model("tenants", "Tenant")
    TenantMembership = apps.get_model("tenants", "TenantMembership")

    for row in PLAN_SEED:
        Plan.objects.update_or_create(key=row["key"], defaults=row)

    founding_plan = Plan.objects.get(key="founding")

    # Every current tenant is a Founding Member (no Solo/Studio/Agency
    # subscribers exist yet). One BillingAccount per owning UserProfile —
    # a user who owns multiple tenants gets a single shared BillingAccount.
    billing_account_by_owner_id: dict[int, int] = {}

    for tenant in Tenant.objects.all():
        if tenant.billing_account_id is not None:
            continue

        owner_membership = (
            TenantMembership.objects.filter(tenant=tenant, role="owner")
            .select_related("user_profile")
            .first()
        )
        if owner_membership is None:
            # No owner on record — nothing to backfill against, leave null.
            continue

        owner_id = owner_membership.user_profile_id
        billing_account_id = billing_account_by_owner_id.get(owner_id)
        if billing_account_id is None:
            billing_account, _ = BillingAccount.objects.get_or_create(
                owner_id=owner_id, defaults={"plan": founding_plan}
            )
            billing_account_id = billing_account.id
            billing_account_by_owner_id[owner_id] = billing_account_id

        tenant.billing_account_id = billing_account_id
        tenant.save(update_fields=["billing_account_id"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0011_plan_billingaccount_tenant_billing_account'),
    ]

    operations = [
        migrations.RunPython(seed_plans_and_backfill, noop_reverse),
    ]

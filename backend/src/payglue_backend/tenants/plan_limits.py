# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""
Plan/feature-limit enforcement for GOGU-138.

Limits are checked live via COUNT() at creation time -- no maintained
counter field, matching the simplicity call made in the GOGU-138
brainstorming (counter/reality drift isn't worth guarding against at
PayGlue's current scale).

A tenant with no billing_account (legacy/unmigrated row -- see migration
0012's backfill, which leaves ownerless tenants unlinked rather than
crashing) is treated as unlimited/exempt, not blocked.
"""
from payglue_backend.core.errors import PlanLimitExceededError
from payglue_backend.tenants.models import BillingAccount, Tenant, TenantMembership


# resource name -> (Plan field name, model, filter kwarg)
_PER_TENANT_RESOURCES: dict[str, tuple[str, type, str]] = {}


def _load_resource_map() -> dict[str, tuple[str, type, str]]:
    # Imported lazily to avoid a tenants -> webhooks import at module load
    # time (webhooks/models.py doesn't import tenants, but keeping this
    # app's own models.py free of a webhooks dependency at import time
    # avoids any future circular-import surprises).
    from payglue_backend.webhooks.models import BuyButton, IntegrationConfig, PaywallConfig, PricingTable

    return {
        "buy buttons": ("max_buy_buttons_per_tenant", BuyButton, "tenant_slug"),
        "paywalls": ("max_paywalls_per_tenant", PaywallConfig, "tenant_slug"),
        "pricing tables": ("max_pricing_tables_per_tenant", PricingTable, "tenant_slug"),
        "payment providers": ("max_providers_per_tenant", IntegrationConfig, "tenant_slug"),
        "team members": ("max_team_members_per_tenant", TenantMembership, "tenant"),
    }


def check_resource_limit(tenant: Tenant, resource: str) -> None:
    """Raise PlanLimitExceededError if creating one more `resource` on
    `tenant` would exceed its billing account's plan limit."""
    billing_account = tenant.billing_account
    if billing_account is None:
        return

    limit_field, model, filter_field = _load_resource_map()[resource]
    limit = getattr(billing_account.plan, limit_field)
    if limit is None:
        return

    filter_value = tenant.slug if filter_field == "tenant_slug" else tenant
    current = model.objects.filter(**{filter_field: filter_value}).count()
    if current >= limit:
        raise PlanLimitExceededError(resource, limit)


def check_new_tenant_limit(billing_account: BillingAccount | None) -> None:
    """Raise PlanLimitExceededError if creating one more tenant/publication
    under `billing_account` would exceed its plan's max_tenants.

    Called before a new Tenant row exists, so it takes the owner's
    BillingAccount directly rather than a Tenant instance.
    """
    if billing_account is None:
        return

    limit = billing_account.plan.max_tenants
    if limit is None:
        return

    current = Tenant.objects.filter(billing_account=billing_account).count()
    if current >= limit:
        raise PlanLimitExceededError("publications", limit)

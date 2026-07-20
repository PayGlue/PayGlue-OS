# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-187: cascade-delete a UserProfile and the tenants they solely own.

Lives outside admin.py (moved here for PG-190) because it's plain business
logic with zero HttpRequest/ModelAdmin coupling -- both the Django Admin
delete flow (tenants/admin.py's UserProfileAdmin) and the automated
delete_lapsed_accounts management command need the exact same behavior,
and neither should import the other.
"""
from payglue_backend.tenants.models import BillingAccount, Tenant, TenantMembership, UserProfile
from payglue_backend.webhooks.models import (
    BuyButton,
    IntegrationConfig,
    PaywallConfig,
    PricingTable,
    ProductMapping,
    TenantProviderCredential,
    WebhookEventRecord,
    WebhookInboundEvent,
)

# PG-187: every one of these is linked to a Tenant only by the tenant_slug
# string column (no real ForeignKey), so nothing here is ever touched by
# Django's own delete-collector -- deleting a Tenant otherwise leaves every
# row below as an orphan. Listed models get a named preview per row; log
# models (append-only, potentially thousands of rows) only get a count --
# see WEBHOOK_LOG_MODELS below.
TENANT_SLUG_CONTENT_MODELS = (
    ("Product mappings", ProductMapping, lambda o: f"{o.payment_provider} · {o.external_product_id} → {o.entitlement_key} ({o.action})"),
    ("Paywalls", PaywallConfig, lambda o: o.name or o.id),
    ("Buy buttons", BuyButton, lambda o: o.name or o.id),
    ("Pricing tables", PricingTable, lambda o: o.name or o.id),
    ("Integration configs", IntegrationConfig, lambda o: o.provider_key),
    # Never render credentials_enc -- provider_key only, per standing "show
    # secrets as dots" convention for anything credential-shaped.
    ("Provider credentials", TenantProviderCredential, lambda o: f"{o.provider_key} (encrypted credential)"),
)

WEBHOOK_LOG_MODELS = (
    ("Webhook inbound events", WebhookInboundEvent),
    ("Webhook event records (idempotency log)", WebhookEventRecord),
)


def tenant_cascade_preview(tenant_slug: str) -> dict:
    """Everything that will be deleted for a tenant, for display only."""
    listed = []
    for label, model, display in TENANT_SLUG_CONTENT_MODELS:
        rows = list(model.objects.filter(tenant_slug=tenant_slug))
        if rows:
            listed.append({"label": label, "items": [display(row) for row in rows]})
    log_counts = []
    for label, model in WEBHOOK_LOG_MODELS:
        count = model.objects.filter(tenant_slug=tenant_slug).count()
        if count:
            log_counts.append({"label": label, "count": count})
    return {"listed": listed, "log_counts": log_counts}


def delete_tenant_cascade(tenant: Tenant) -> None:
    """Actually deletes a tenant and every tenant_slug-linked row for it.

    Must run inside the same transaction as the UserProfile delete that
    triggered it, so a failure partway through can't leave a half-deleted
    tenant. BillingProfile and TenantMembership are real ForeignKeys with
    on_delete=CASCADE, so tenant.delete() takes care of those on its own --
    only the tenant_slug-linked models below need explicit cleanup.
    """
    for _label, model, _display in TENANT_SLUG_CONTENT_MODELS:
        model.objects.filter(tenant_slug=tenant.slug).delete()
    for _label, model in WEBHOOK_LOG_MODELS:
        model.objects.filter(tenant_slug=tenant.slug).delete()
    tenant.delete()


def sole_and_shared_tenants(profile: UserProfile) -> tuple[list[Tenant], list[Tenant]]:
    """Splits this user's tenant memberships into tenants they solely own
    (deleted entirely, cascade and all) vs. tenants with other owners
    (only this user's membership is removed, tenant stays untouched)."""
    sole_owner_tenants: list[Tenant] = []
    shared_tenants: list[Tenant] = []
    for membership in profile.tenant_memberships.select_related("tenant"):
        if membership.role == TenantMembership.Role.OWNER:
            other_owner_exists = (
                TenantMembership.objects.filter(
                    tenant=membership.tenant, role=TenantMembership.Role.OWNER
                )
                .exclude(pk=membership.pk)
                .exists()
            )
            if not other_owner_exists:
                sole_owner_tenants.append(membership.tenant)
                continue
        shared_tenants.append(membership.tenant)
    return sole_owner_tenants, shared_tenants


def clear_shared_tenant_billing_links(profile: UserProfile, shared_tenants: list[Tenant]) -> None:
    """PG-190: a shared (kept-alive) tenant can still point at this
    profile's own BillingAccount via Tenant.billing_account -- a real
    ForeignKey with on_delete=PROTECT. Deleting the profile cascades to
    delete their BillingAccount too (OneToOneField, on_delete=CASCADE),
    which would otherwise crash with ProtectedError against that guard on a
    tenant we're deliberately keeping alive. Found live via a Postgres test
    run, not by inspection -- this same crash was already latent in PG-187's
    original admin delete flow, just never exercised by its tests.

    Clearing the link (the field is nullable) is the safe default: it loses
    which BillingAccount currently pays for the tenant, but a legitimate
    re-link to a remaining co-owner's BillingAccount is a separate,
    not-yet-built flow -- better to leave it unset than to crash the whole
    deletion or silently guess a replacement owner.

    Uses .update(), not .save() per tenant -- Tenant inherits django_tenants'
    TenantMixin, whose save() re-checks/creates the Postgres schema on every
    write; a plain FK clear has no business touching that.
    """
    billing_account: BillingAccount | None = getattr(profile, "billing_account", None)
    if billing_account is None:
        return
    stale_tenant_ids = [t.pk for t in shared_tenants if t.billing_account_id == billing_account.pk]
    if stale_tenant_ids:
        Tenant.objects.filter(pk__in=stale_tenant_ids).update(billing_account=None)

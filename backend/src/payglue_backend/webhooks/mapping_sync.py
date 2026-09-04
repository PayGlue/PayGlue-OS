# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Keep the rule for a product in step with the widgets that offer it (PG-254).

## Why this is not in the browser any more

A buy button, a paywall and a pricing tier each used to save themselves and then
make a second call to create or update the matching `ProductMapping`, choosing
between create and update by searching a list of mappings the page had loaded
earlier. Everything that can go wrong with that did:

* the second call could fail on its own, leaving a widget that takes money and
  grants nothing while the event log reports "processed" (PG-233)
* the search ran against a list that could be stale, so it chose "create" for a
  row that already existed and got a 400 back from the constraint
* each editor invented its own `entitlement_key`, which is how one product ended
  up with several rules (PG-254)

None of that is a browser's job. A widget knows which product it points at; what
happens when somebody buys that product is a fact about the tenant, and the
server owns it. Callers here run inside the same transaction as the widget save,
so either both exist or neither does.

## What a rule is keyed on

The five fields of the unique constraint: tenant, provider, event type, product,
action. `entitlement_key` is deliberately not among them. It is the readable
name of what gets granted, it reaches Ghost as `product:<key>`, and it is written
once when the rule is created and never touched again. Existing keys like `pro`
and `founding_member` therefore survive, and so do the labels already on members.

## What is deliberately not done here

Deleting. Removing a buy button from your site does not un-sell the product: a
checkout link that is already out in the world keeps working, and a purchase
through it still has to grant what it promised. So a rule outlives the widget
that created it. That is also what happened before this module existed, so it is
not a change in behaviour, and it is the safe direction: a rule too many grants
what somebody paid for, a rule too few takes their money and gives them nothing.
"""

from dataclasses import dataclass, field

from payglue_backend.webhooks.models import ProductMapping


@dataclass(frozen=True)
class GrantSpec:
    """What a widget knows about the product it offers."""

    provider: str
    product_id: str
    event_type: str
    # Used only when the rule is created. An existing rule keeps its own name,
    # because it is already written onto members as a Ghost label.
    entitlement_key: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        """A widget without a provider or a product offers nothing to map."""
        return bool(self.provider.strip() and self.product_id.strip())


def _default_entitlement_key(spec: GrantSpec) -> str:
    """Mirrors what the pricing table editor used to write on its own."""
    return f"product-{spec.product_id.strip()}"


def sync_grant(tenant_slug: str, spec: GrantSpec) -> ProductMapping | None:
    """Make sure buying this product does what the widget says it does.

    Returns the rule, or None when the widget names no product. Safe to call
    twice with the same arguments, and safe to call from two widgets that point
    at the same product: the second call updates the first one's rule rather
    than adding a competing one.
    """
    if not spec.is_complete:
        return None

    identity = {
        "tenant_slug": tenant_slug,
        "payment_provider": spec.provider.strip(),
        "event_type": spec.event_type.strip() or "order.paid",
        "external_product_id": spec.product_id.strip(),
        "action": ProductMapping.Action.GRANT,
    }
    # `defaults` applies on update, `create_defaults` on create, so the key is
    # set once and then left alone.
    on_update = {"metadata": dict(spec.metadata), "is_active": True}
    on_create = {
        **on_update,
        "quantity": 1,
        "entitlement_key": spec.entitlement_key.strip() or _default_entitlement_key(spec),
    }

    mapping, _ = ProductMapping.objects.update_or_create(
        **identity, defaults=on_update, create_defaults=on_create
    )
    return mapping


def widgets_offering(tenant_slug: str, product_ids: list[str]) -> dict[str, list[str]]:
    """Which widgets currently offer each product, as readable labels.

    Answers "where is this sold" by asking the widgets, which is the only place
    that knows. It used to be answered from `source_name` in the rule's own
    metadata, written by whichever editor saved last. With one rule per product
    that stopped being merely incomplete and started being wrong: a product on
    both a buy button and a pricing tier reported only the tier, because the
    tier was saved second (PG-254).

    Deliberately computed rather than stored. A stored list would have to be
    kept in step with every widget save and delete, and keeping the same fact in
    two places is what this whole change is about.
    """
    from payglue_backend.webhooks.models import BuyButton, PaywallConfig, PricingTier

    wanted = {p for p in product_ids if p}
    if not wanted:
        return {}

    offers: dict[str, list[str]] = {product: [] for product in wanted}

    for button in BuyButton.objects.filter(tenant_slug=tenant_slug, product_id__in=wanted):
        offers[button.product_id].append(f"Buy Button: {button.name}")

    for paywall in PaywallConfig.objects.filter(tenant_slug=tenant_slug, product_id__in=wanted):
        offers[paywall.product_id].append(f"Paywall: {paywall.name}")

    tiers = PricingTier.objects.filter(
        table__tenant_slug=tenant_slug, product_id__in=wanted
    ).select_related("table")
    for tier in tiers:
        offers[tier.product_id].append(f"Pricing Table: {tier.table.name} · {tier.name}")

    return {product: sorted(labels) for product, labels in offers.items() if labels}


def sync_grants(tenant_slug: str, specs: list[GrantSpec]) -> list[ProductMapping]:
    """The pricing-table case: several tiers saved in one go.

    Two tiers on the same product are not an error and not a duplicate. They are
    two places offering one thing, and they resolve to one rule, which is the
    whole point of keying on the product.
    """
    rules = []
    for spec in specs:
        mapping = sync_grant(tenant_slug, spec)
        if mapping is not None:
            rules.append(mapping)
    return rules

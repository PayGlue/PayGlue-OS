# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from collections import defaultdict
from collections.abc import Sequence

from payglue_backend.core.interfaces import MappingResolver
from payglue_backend.core.models import (
    CanonicalPaymentEvent,
    EntitlementInstruction,
    TenantContext,
)
from payglue_backend.webhooks.models import ProductMapping


# The two questions a payment event can answer, and the only two that matter.
#
# The event type used to be part of the mapping lookup, which made it a third
# question: "and which of these words did the rule happen to be saved with".
# Nobody could answer it. No widget ever sent the field, so `views.py` wrote
# `order.paid` on every rule it created, and a provider that announces a
# subscription with `subscription.active` then matched nothing at all. The
# purchase went through, the event was recorded as processed, and the reader
# got no access (PG-257).
#
# The type also never reached the outcome: an EntitlementInstruction carries
# the key, the action and the quantity, and none of them come from it. So it
# only ever decided whether anything happened, never what.
_PURCHASE_EVENTS = frozenset({"order.paid", "subscription.active"})

# The mirror image, and the one that cost money the other way round.
# `subscription.revoked` appeared nowhere in this file and in no test, while
# three adapters emit it for the ordinary end of a subscription: Lemon Squeezy
# for `subscription_expired`, PayPal for `BILLING.SUBSCRIPTION.EXPIRED`, and
# Gumroad when a subscription ends. Access was therefore never withdrawn when
# a subscription simply ran out, only when somebody actively cancelled.
#
# Payment trouble deliberately does not appear here. `past_due` and
# `payment_failed` are in no adapter's map at all, so they never reach this
# code: the provider chases the customer, and the customer decides. What is in
# here is reversible anyway, since `resumed`, `unpaused` and `RE-ACTIVATED`
# all map back to `subscription.active`.
_ENDING_EVENTS = frozenset({"subscription.canceled", "subscription.revoked"})


def _one_rule_per_product(
    mappings: Sequence[ProductMapping], line_item_quantities: dict[str, int]
):
    """Yield (mapping, quantity) for each purchased product, once.

    Since PG-254 the unique constraint makes a second rule for the same product
    impossible, so on a healthy table nothing is ever skipped here. It stays as
    the belt to that constraint's braces: a row written before the migration on
    an installation that has not run it yet, or one restored from an old backup,
    would otherwise be applied on top of the current rule, in id order, and
    quietly decide the member's newsletter flag and labels.

    Keyed on the product rather than on the entitlement key, which is what
    `_revoke_all_for_provider` dedupes on. The key is a name for what gets
    granted and two rules can share it. The product is the thing the payment
    actually identifies.
    """
    already_answered: set[str] = set()
    for mapping in mappings:
        quantity = line_item_quantities.get(mapping.external_product_id)
        if quantity is None or mapping.external_product_id in already_answered:
            continue
        already_answered.add(mapping.external_product_id)
        yield mapping, quantity


class DbProductMappingResolver(MappingResolver):
    def resolve(
        self, event: CanonicalPaymentEvent, tenant_ctx: TenantContext
    ) -> Sequence[EntitlementInstruction]:
        line_item_quantities: dict[str, int] = defaultdict(int)
        for line_item in event.line_items:
            line_item_quantities[line_item.external_product_id] += line_item.quantity

        if not line_item_quantities:
            # PG-123: a cancellation that carries no product/tier id means
            # "revoke everything this provider grants for this member" --
            # currently only Patreon, whose delete webhook doesn't reliably
            # carry the tier the patron was on, so revoke-all is keyed on the
            # trigger alone (see PatreonPaymentAdapter). Every other provider
            # always sends a product id on cancel, so it never reaches here.
            if event.event_type in _ENDING_EVENTS:
                return self._revoke_all_for_provider(event, tenant_ctx)
            return ()

        # A purchase matches a rule for the product, whichever purchase word
        # the rule was stored with. Anything else still matches exactly, so a
        # cancellation can never pick up a grant rule here and hand out access.
        if event.event_type in _PURCHASE_EVENTS:
            type_filter = {"event_type__in": _PURCHASE_EVENTS}
        else:
            type_filter = {"event_type": event.event_type}

        mappings = ProductMapping.objects.filter(
            tenant_slug=tenant_ctx.tenant_slug,
            payment_provider=event.provider,
            external_product_id__in=line_item_quantities.keys(),
            is_active=True,
            **type_filter,
        ).order_by("id")

        instructions: list[EntitlementInstruction] = []
        for mapping, line_item_quantity in _one_rule_per_product(
            mappings, line_item_quantities
        ):
            meta = dict(mapping.metadata) if mapping.metadata else {}
            meta["_provider"] = event.provider
            meta["_event_id"] = event.provider_event_id
            meta["_product_id"] = mapping.external_product_id
            meta["_occurred_at"] = event.occurred_at.date().isoformat()
            instructions.append(
                EntitlementInstruction(
                    entitlement_key=mapping.entitlement_key,
                    action=mapping.action,
                    quantity=mapping.quantity * line_item_quantity,
                    metadata=meta,
                )
            )

        # An ending with no rule of its own falls back to the rule that granted
        # the access in the first place, with the action flipped to "revoke".
        # Reached for both endings now: an expiry used to fall through here and
        # leave the reader holding a label they no longer pay for.
        if not instructions and event.event_type in _ENDING_EVENTS:
            fallback_mappings = ProductMapping.objects.filter(
                tenant_slug=tenant_ctx.tenant_slug,
                payment_provider=event.provider,
                event_type__in=_PURCHASE_EVENTS,
                external_product_id__in=line_item_quantities.keys(),
                is_active=True,
            ).order_by("id")
            for mapping, line_item_quantity in _one_rule_per_product(
                fallback_mappings, line_item_quantities
            ):
                # Same context as the two paths above. It was missing here, so
                # every cancellation that came through the fallback reached the
                # CMS without a provider, a product or a date.
                meta = dict(mapping.metadata) if mapping.metadata else {}
                meta["_provider"] = event.provider
                meta["_event_id"] = event.provider_event_id
                meta["_product_id"] = mapping.external_product_id
                meta["_occurred_at"] = event.occurred_at.date().isoformat()
                instructions.append(
                    EntitlementInstruction(
                        entitlement_key=mapping.entitlement_key,
                        action="revoke",
                        quantity=mapping.quantity * line_item_quantity,
                        metadata=meta,
                    )
                )

        return tuple(instructions)

    def _revoke_all_for_provider(
        self, event: CanonicalPaymentEvent, tenant_ctx: TenantContext
    ) -> Sequence[EntitlementInstruction]:
        """Revoke every distinct entitlement this provider can grant for the
        tenant. Used for Patreon cancellations, which don't carry the tier id
        to target a specific mapping. Revoking a Ghost label/comp the member
        doesn't actually hold is a harmless no-op downstream, so revoking the
        full set is safe."""
        mappings = ProductMapping.objects.filter(
            tenant_slug=tenant_ctx.tenant_slug,
            payment_provider=event.provider,
            is_active=True,
        ).order_by("id")

        seen: set[str] = set()
        instructions: list[EntitlementInstruction] = []
        for mapping in mappings:
            if mapping.entitlement_key in seen:
                continue
            seen.add(mapping.entitlement_key)
            meta = dict(mapping.metadata) if mapping.metadata else {}
            meta["_provider"] = event.provider
            meta["_event_id"] = event.provider_event_id
            meta["_occurred_at"] = event.occurred_at.date().isoformat()
            instructions.append(
                EntitlementInstruction(
                    entitlement_key=mapping.entitlement_key,
                    action="revoke",
                    quantity=mapping.quantity,
                    metadata=meta,
                )
            )
        return tuple(instructions)

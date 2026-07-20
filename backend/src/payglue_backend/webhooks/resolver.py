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
            if event.event_type == "subscription.canceled":
                return self._revoke_all_for_provider(event, tenant_ctx)
            return ()

        mappings = ProductMapping.objects.filter(
            tenant_slug=tenant_ctx.tenant_slug,
            payment_provider=event.provider,
            event_type=event.event_type,
            external_product_id__in=line_item_quantities.keys(),
            is_active=True,
        ).order_by("id")

        instructions: list[EntitlementInstruction] = []
        for mapping in mappings:
            line_item_quantity = line_item_quantities.get(mapping.external_product_id)
            if line_item_quantity is None:
                continue
            meta = dict(mapping.metadata) if mapping.metadata else {}
            meta["_provider"] = event.provider
            meta["_event_id"] = event.provider_event_id
            meta["_product_id"] = mapping.external_product_id
            instructions.append(
                EntitlementInstruction(
                    entitlement_key=mapping.entitlement_key,
                    action=mapping.action,
                    quantity=mapping.quantity * line_item_quantity,
                    metadata=meta,
                )
            )

        # For cancellation events with no explicit mapping, fall back to the
        # order.paid mapping for the same products and flip the action to "revoke".
        if not instructions and event.event_type == "subscription.canceled":
            fallback_mappings = ProductMapping.objects.filter(
                tenant_slug=tenant_ctx.tenant_slug,
                payment_provider=event.provider,
                event_type="order.paid",
                external_product_id__in=line_item_quantities.keys(),
                is_active=True,
            ).order_by("id")
            for mapping in fallback_mappings:
                line_item_quantity = line_item_quantities.get(mapping.external_product_id)
                if line_item_quantity is None:
                    continue
                instructions.append(
                    EntitlementInstruction(
                        entitlement_key=mapping.entitlement_key,
                        action="revoke",
                        quantity=mapping.quantity * line_item_quantity,
                        metadata=dict(mapping.metadata) if mapping.metadata else {},
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
            instructions.append(
                EntitlementInstruction(
                    entitlement_key=mapping.entitlement_key,
                    action="revoke",
                    quantity=mapping.quantity,
                    metadata=meta,
                )
            )
        return tuple(instructions)

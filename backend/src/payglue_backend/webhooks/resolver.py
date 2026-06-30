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

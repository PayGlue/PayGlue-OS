# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from collections.abc import Sequence

from payglue_backend.core.interfaces import MappingResolver
from payglue_backend.core.models import (
    CanonicalPaymentEvent,
    EntitlementInstruction,
    TenantContext,
)


class StaticMappingResolver(MappingResolver):
    def __init__(
        self,
        mapping: dict[
            str,
            dict[str, Sequence[EntitlementInstruction]]
            | Sequence[EntitlementInstruction],
        ],
    ) -> None:
        self._mapping = mapping

    def resolve(
        self, event: CanonicalPaymentEvent, tenant_ctx: TenantContext
    ) -> Sequence[EntitlementInstruction]:
        scoped = self._mapping.get(tenant_ctx.tenant_slug)
        if isinstance(scoped, dict):
            return scoped.get(event.event_type, ())

        fallback = self._mapping.get("*")
        if isinstance(fallback, dict):
            return fallback.get(event.event_type, ())

        legacy = self._mapping.get(event.event_type)
        if isinstance(legacy, Sequence):
            return legacy

        return ()

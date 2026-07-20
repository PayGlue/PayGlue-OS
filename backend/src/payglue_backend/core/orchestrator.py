# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from dataclasses import dataclass
from typing import Mapping
from typing import Literal

from payglue_backend.core.errors import (
    MissingCustomerIdentityError,
    UnsupportedEventTypeError,
)
from payglue_backend.core.interfaces import IdempotencyStore, MappingResolver
from payglue_backend.core.models import TenantContext
from payglue_backend.core.registry import AdapterRegistry


@dataclass(frozen=True)
class OrchestrationResult:
    status: Literal["duplicate", "processed"]
    event_id: str
    applied_count: int


class WebhookOrchestrator:
    def __init__(
        self,
        adapter_registry: AdapterRegistry,
        mapping_resolver: MappingResolver,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._adapter_registry = adapter_registry
        self._mapping_resolver = mapping_resolver
        self._idempotency_store = idempotency_store

    def process_webhook(
        self,
        payment_provider_key: str,
        cms_provider_key: str,
        raw_body: bytes,
        headers: Mapping[str, str],
        tenant_ctx: TenantContext,
        skip_verification: bool = False,
    ) -> OrchestrationResult:
        payment_adapter = self._adapter_registry.get_payment(payment_provider_key)
        cms_adapter = self._adapter_registry.get_cms(cms_provider_key)

        if not skip_verification:
            payment_adapter.verify_webhook(raw_body, headers, tenant_ctx)
        event = payment_adapter.parse_event(raw_body, headers, tenant_ctx)

        if not payment_adapter.supports_event(event.event_type):
            raise UnsupportedEventTypeError(
                f"Unsupported event type: {event.event_type}"
            )

        idempotency_key = self._build_idempotency_key(
            tenant_ctx.tenant_slug, event.provider, event.provider_event_id
        )
        if not self._idempotency_store.start_processing(idempotency_key):
            return OrchestrationResult(
                status="duplicate", event_id=event.provider_event_id, applied_count=0
            )

        try:
            instructions = self._mapping_resolver.resolve(event, tenant_ctx)
            if event.customer.email is None and event.customer.external_id is None:
                raise MissingCustomerIdentityError(
                    "payment event does not include customer email or external id"
                )

            applied = 0
            for instruction in instructions:
                cms_adapter.apply_entitlement(event.customer, instruction, tenant_ctx)
                applied += 1
        except Exception:
            self._idempotency_store.release(idempotency_key)
            raise

        self._idempotency_store.mark_processed(idempotency_key)

        return OrchestrationResult(
            status="processed", event_id=event.provider_event_id, applied_count=applied
        )

    @staticmethod
    def _build_idempotency_key(
        tenant_slug: str, provider: str, provider_event_id: str
    ) -> str:
        return f"{tenant_slug}:{provider}:{provider_event_id}"

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from collections.abc import Mapping, Sequence
from typing import Protocol

from payglue_backend.core.models import (
    CanonicalCustomer,
    CanonicalPaymentEvent,
    EntitlementInstruction,
    TenantContext,
)


class PaymentAdapter(Protocol):
    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> None: ...

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> CanonicalPaymentEvent: ...

    def supports_event(self, event_type: str) -> bool: ...

    def health_check(self, tenant_ctx: TenantContext) -> Mapping[str, object]: ...


class CmsAdapter(Protocol):
    def apply_entitlement(
        self,
        customer: CanonicalCustomer,
        instruction: EntitlementInstruction,
        tenant_ctx: TenantContext,
    ) -> None: ...

    def health_check(self, tenant_ctx: TenantContext) -> Mapping[str, object]: ...


class IdempotencyStore(Protocol):
    def start_processing(self, idempotency_key: str) -> bool: ...

    def mark_processed(self, idempotency_key: str) -> None: ...

    def release(self, idempotency_key: str) -> None: ...


class MappingResolver(Protocol):
    def resolve(
        self, event: CanonicalPaymentEvent, tenant_ctx: TenantContext
    ) -> Sequence[EntitlementInstruction]: ...


class CredentialProvider(Protocol):
    def set_credentials(
        self,
        tenant_ctx: TenantContext,
        provider_key: str,
        credentials: Mapping[str, str],
    ) -> Mapping[str, object]: ...

    def get_credentials(
        self,
        tenant_ctx: TenantContext,
        provider_key: str,
    ) -> Mapping[str, str]: ...

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TenantContext:
    tenant_slug: str
    tenant_id: int | None = None
    schema_name: str | None = None


@dataclass(frozen=True)
class CanonicalCustomer:
    email: str | None = None
    external_id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class CanonicalLineItem:
    external_product_id: str
    quantity: int
    amount_minor: int
    currency: str


@dataclass(frozen=True)
class CanonicalPaymentEvent:
    provider: str
    provider_event_id: str
    event_type: str
    occurred_at: datetime
    customer: CanonicalCustomer
    line_items: tuple[CanonicalLineItem, ...]
    status: str


@dataclass(frozen=True)
class EntitlementInstruction:
    entitlement_key: str
    action: str
    quantity: int = 1
    metadata: dict = field(default_factory=dict)

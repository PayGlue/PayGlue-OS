from datetime import UTC, datetime
from typing import Mapping

import pytest

from payglue_backend.core.mapping import StaticMappingResolver
from payglue_backend.core.models import (
    CanonicalCustomer,
    CanonicalLineItem,
    CanonicalPaymentEvent,
    EntitlementInstruction,
    TenantContext,
)
from payglue_backend.core.orchestrator import WebhookOrchestrator
from payglue_backend.core.registry import AdapterRegistry
from payglue_backend.webhooks.idempotency import DbIdempotencyStore
from payglue_backend.webhooks.models import WebhookEventRecord


class StubPaymentAdapter:
    def __init__(self, event: CanonicalPaymentEvent) -> None:
        self._event = event

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> None:
        del raw_body, headers, tenant_ctx

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> CanonicalPaymentEvent:
        del raw_body, headers, tenant_ctx
        return self._event

    def supports_event(self, event_type: str) -> bool:
        return event_type == self._event.event_type


class StubCmsAdapter:
    def __init__(self) -> None:
        self.applied: list[tuple[str, EntitlementInstruction, TenantContext]] = []

    def apply_entitlement(
        self,
        customer_ref: str,
        instruction: EntitlementInstruction,
        tenant_ctx: TenantContext,
    ) -> None:
        self.applied.append((customer_ref, instruction, tenant_ctx))


def make_event() -> CanonicalPaymentEvent:
    return CanonicalPaymentEvent(
        provider="polar",
        provider_event_id="evt_db_001",
        event_type="order.paid",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        customer=CanonicalCustomer(email="owner@example.com", external_id="cus_001"),
        line_items=(
            CanonicalLineItem(
                external_product_id="prod_123",
                quantity=1,
                amount_minor=1000,
                currency="USD",
            ),
        ),
        status="paid",
    )


@pytest.mark.django_db
def test_orchestrator_uses_db_idempotency_store_for_duplicates() -> None:
    payment_adapter = StubPaymentAdapter(make_event())
    cms_adapter = StubCmsAdapter()
    registry = AdapterRegistry()
    registry.register_payment("polar", payment_adapter)
    registry.register_cms("ghost", cms_adapter)

    resolver = StaticMappingResolver(
        {
            "order.paid": [
                EntitlementInstruction(
                    entitlement_key="tier.basic",
                    action="grant",
                    quantity=1,
                )
            ]
        }
    )
    orchestrator = WebhookOrchestrator(
        adapter_registry=registry,
        mapping_resolver=resolver,
        idempotency_store=DbIdempotencyStore(),
    )
    tenant_ctx = TenantContext(tenant_slug="tenant-a")

    first = orchestrator.process_webhook("polar", "ghost", b"{}", {}, tenant_ctx)
    second = orchestrator.process_webhook("polar", "ghost", b"{}", {}, tenant_ctx)

    assert first.status == "processed"
    assert second.status == "duplicate"
    assert len(cms_adapter.applied) == 1
    record = WebhookEventRecord.objects.get(idempotency_key="tenant-a:polar:evt_db_001")
    assert record.status == WebhookEventRecord.Status.PROCESSED

from datetime import UTC, datetime
from typing import Mapping

import pytest

from payglue_backend.core.errors import (
    InvalidWebhookSignatureError,
    MissingCustomerIdentityError,
    UnsupportedEventTypeError,
)
from payglue_backend.core.idempotency import InMemoryIdempotencyStore
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


class StubPaymentAdapter:
    def __init__(
        self,
        event: CanonicalPaymentEvent,
        signature_valid: bool = True,
        supported_event_types: set[str] | None = None,
    ) -> None:
        self._event = event
        self._signature_valid = signature_valid
        self._supported_event_types = supported_event_types or {event.event_type}

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> None:
        del raw_body, headers, tenant_ctx
        if not self._signature_valid:
            raise InvalidWebhookSignatureError("invalid signature")

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> CanonicalPaymentEvent:
        del raw_body, headers
        return self._event

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._supported_event_types


class StubCmsAdapter:
    def __init__(self, should_fail: bool = False) -> None:
        self.applied: list[tuple[CanonicalCustomer, EntitlementInstruction, TenantContext]] = []
        self._should_fail = should_fail

    def apply_entitlement(
        self,
        customer: CanonicalCustomer,
        instruction: EntitlementInstruction,
        tenant_ctx: TenantContext,
    ) -> None:
        if self._should_fail:
            raise RuntimeError("temporary cms failure")
        self.applied.append((customer, instruction, tenant_ctx))


def make_event(provider_event_id: str = "evt_123") -> CanonicalPaymentEvent:
    return CanonicalPaymentEvent(
        provider="polar",
        provider_event_id=provider_event_id,
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


def make_event_without_customer() -> CanonicalPaymentEvent:
    return CanonicalPaymentEvent(
        provider="polar",
        provider_event_id="evt_no_customer",
        event_type="order.paid",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        customer=CanonicalCustomer(email=None, external_id=None),
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


def make_event_email_only() -> CanonicalPaymentEvent:
    return CanonicalPaymentEvent(
        provider="polar",
        provider_event_id="evt_email_only",
        event_type="order.paid",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        customer=CanonicalCustomer(email="email-only@example.com", external_id=None),
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


def build_orchestrator(
    payment_adapter: StubPaymentAdapter, cms_adapter: StubCmsAdapter
) -> WebhookOrchestrator:
    registry = AdapterRegistry()
    registry.register_payment("polar", payment_adapter)
    registry.register_cms("ghost", cms_adapter)
    resolver = StaticMappingResolver(
        {
            "order.paid": [
                EntitlementInstruction(
                    entitlement_key="tier.basic", action="grant", quantity=1
                )
            ]
        }
    )
    return WebhookOrchestrator(
        adapter_registry=registry,
        mapping_resolver=resolver,
        idempotency_store=InMemoryIdempotencyStore(),
    )


def test_orchestrator_raises_on_invalid_signature() -> None:
    payment = StubPaymentAdapter(event=make_event(), signature_valid=False)
    cms = StubCmsAdapter()
    orchestrator = build_orchestrator(payment, cms)

    with pytest.raises(InvalidWebhookSignatureError):
        orchestrator.process_webhook(
            payment_provider_key="polar",
            cms_provider_key="ghost",
            raw_body=b"{}",
            headers={},
            tenant_ctx=TenantContext(tenant_slug="tenant-a"),
        )


def test_orchestrator_short_circuits_when_event_is_duplicate() -> None:
    payment = StubPaymentAdapter(event=make_event())
    cms = StubCmsAdapter()
    orchestrator = build_orchestrator(payment, cms)
    tenant_ctx = TenantContext(tenant_slug="tenant-a")

    first = orchestrator.process_webhook("polar", "ghost", b"{}", {}, tenant_ctx)
    second = orchestrator.process_webhook("polar", "ghost", b"{}", {}, tenant_ctx)

    assert first.status == "processed"
    assert second.status == "duplicate"
    assert len(cms.applied) == 1


def test_orchestrator_processes_event_and_applies_entitlements() -> None:
    payment = StubPaymentAdapter(event=make_event())
    cms = StubCmsAdapter()
    orchestrator = build_orchestrator(payment, cms)

    result = orchestrator.process_webhook(
        payment_provider_key="polar",
        cms_provider_key="ghost",
        raw_body=b"{}",
        headers={},
        tenant_ctx=TenantContext(tenant_slug="tenant-a"),
    )

    assert result.status == "processed"
    assert result.applied_count == 1
    assert len(cms.applied) == 1
    customer, instruction, tenant_ctx = cms.applied[0]
    assert customer.email == "owner@example.com"
    assert customer.external_id == "cus_001"
    assert instruction.entitlement_key == "tier.basic"
    assert tenant_ctx.tenant_slug == "tenant-a"


def test_idempotency_is_isolated_by_tenant_slug() -> None:
    payment = StubPaymentAdapter(event=make_event(provider_event_id="evt_shared"))
    cms = StubCmsAdapter()
    orchestrator = build_orchestrator(payment, cms)

    first = orchestrator.process_webhook(
        payment_provider_key="polar",
        cms_provider_key="ghost",
        raw_body=b"{}",
        headers={},
        tenant_ctx=TenantContext(tenant_slug="tenant-a"),
    )
    second = orchestrator.process_webhook(
        payment_provider_key="polar",
        cms_provider_key="ghost",
        raw_body=b"{}",
        headers={},
        tenant_ctx=TenantContext(tenant_slug="tenant-b"),
    )

    assert first.status == "processed"
    assert second.status == "processed"
    assert len(cms.applied) == 2


def test_orchestrator_retries_after_processing_failure() -> None:
    payment = StubPaymentAdapter(event=make_event(provider_event_id="evt_retryable"))
    failing_cms = StubCmsAdapter(should_fail=True)
    orchestrator = build_orchestrator(payment, failing_cms)
    tenant_ctx = TenantContext(tenant_slug="tenant-a")

    with pytest.raises(RuntimeError):
        orchestrator.process_webhook("polar", "ghost", b"{}", {}, tenant_ctx)

    healthy_cms = StubCmsAdapter()
    registry = AdapterRegistry()
    registry.register_payment("polar", payment)
    registry.register_cms("ghost", healthy_cms)
    resolver = StaticMappingResolver(
        {
            "*": {
                "order.paid": [
                    EntitlementInstruction(
                        entitlement_key="tier.basic", action="grant", quantity=1
                    )
                ]
            }
        }
    )
    orchestrator_retry = WebhookOrchestrator(
        adapter_registry=registry,
        mapping_resolver=resolver,
        idempotency_store=orchestrator._idempotency_store,
    )

    result = orchestrator_retry.process_webhook("polar", "ghost", b"{}", {}, tenant_ctx)

    assert result.status == "processed"
    assert len(healthy_cms.applied) == 1


def test_orchestrator_raises_when_event_type_unsupported() -> None:
    event = CanonicalPaymentEvent(
        provider="polar",
        provider_event_id="evt_unsupported",
        event_type="order.unknown",
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
    payment = StubPaymentAdapter(event=event, supported_event_types={"order.paid"})
    cms = StubCmsAdapter()
    orchestrator = build_orchestrator(payment, cms)

    with pytest.raises(UnsupportedEventTypeError):
        orchestrator.process_webhook(
            payment_provider_key="polar",
            cms_provider_key="ghost",
            raw_body=b"{}",
            headers={},
            tenant_ctx=TenantContext(tenant_slug="tenant-a"),
        )


def test_orchestrator_requires_customer_identity() -> None:
    payment = StubPaymentAdapter(event=make_event_without_customer())
    cms = StubCmsAdapter()
    orchestrator = build_orchestrator(payment, cms)

    with pytest.raises(MissingCustomerIdentityError):
        orchestrator.process_webhook(
            payment_provider_key="polar",
            cms_provider_key="ghost",
            raw_body=b"{}",
            headers={},
            tenant_ctx=TenantContext(tenant_slug="tenant-a"),
        )


def test_orchestrator_falls_back_to_customer_email_when_external_id_missing() -> None:
    payment = StubPaymentAdapter(event=make_event_email_only())
    cms = StubCmsAdapter()
    orchestrator = build_orchestrator(payment, cms)

    result = orchestrator.process_webhook(
        payment_provider_key="polar",
        cms_provider_key="ghost",
        raw_body=b"{}",
        headers={},
        tenant_ctx=TenantContext(tenant_slug="tenant-a"),
    )

    assert result.status == "processed"
    assert len(cms.applied) == 1
    customer, _, _ = cms.applied[0]
    assert customer.email == "email-only@example.com"
    assert customer.external_id is None

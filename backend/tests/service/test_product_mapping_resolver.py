from datetime import UTC, datetime

import pytest

from payglue_backend.core.models import (
    CanonicalCustomer,
    CanonicalLineItem,
    CanonicalPaymentEvent,
    TenantContext,
)
from payglue_backend.webhooks.models import ProductMapping
from payglue_backend.webhooks.resolver import DbProductMappingResolver


pytestmark = pytest.mark.django_db


def _event(line_items: tuple[CanonicalLineItem, ...]) -> CanonicalPaymentEvent:
    return CanonicalPaymentEvent(
        provider="polar",
        provider_event_id="evt_1",
        event_type="order.paid",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        customer=CanonicalCustomer(email="x@example.com", external_id="cus_1"),
        line_items=line_items,
        status="paid",
    )


def test_resolver_returns_single_mapping_with_line_item_quantity_multiplier() -> None:
    ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="polar",
        event_type="order.paid",
        external_product_id="prod_basic",
        entitlement_key="tier.basic",
        action="grant",
        quantity=3,
        is_active=True,
    )
    resolver = DbProductMappingResolver()

    instructions = resolver.resolve(
        _event(
            (
                CanonicalLineItem(
                    external_product_id="prod_basic",
                    quantity=2,
                    amount_minor=1000,
                    currency="USD",
                ),
            )
        ),
        TenantContext(tenant_slug="tenant-a"),
    )

    assert len(instructions) == 1
    assert instructions[0].entitlement_key == "tier.basic"
    assert instructions[0].quantity == 6


def test_resolver_returns_multiple_mappings_for_multiple_line_items() -> None:
    ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="polar",
        event_type="order.paid",
        external_product_id="prod_basic",
        entitlement_key="tier.basic",
        action="grant",
        quantity=1,
        is_active=True,
    )
    ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="polar",
        event_type="order.paid",
        external_product_id="prod_pro",
        entitlement_key="tier.pro",
        action="grant",
        quantity=1,
        is_active=True,
    )
    resolver = DbProductMappingResolver()

    instructions = resolver.resolve(
        _event(
            (
                CanonicalLineItem(
                    external_product_id="prod_basic",
                    quantity=1,
                    amount_minor=1000,
                    currency="USD",
                ),
                CanonicalLineItem(
                    external_product_id="prod_pro",
                    quantity=1,
                    amount_minor=2000,
                    currency="USD",
                ),
            )
        ),
        TenantContext(tenant_slug="tenant-a"),
    )

    assert {item.entitlement_key for item in instructions} == {"tier.basic", "tier.pro"}


def test_resolver_ignores_inactive_mappings() -> None:
    ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="polar",
        event_type="order.paid",
        external_product_id="prod_basic",
        entitlement_key="tier.basic",
        action="grant",
        quantity=1,
        is_active=False,
    )

    resolver = DbProductMappingResolver()
    instructions = resolver.resolve(
        _event(
            (
                CanonicalLineItem(
                    external_product_id="prod_basic",
                    quantity=1,
                    amount_minor=1000,
                    currency="USD",
                ),
            )
        ),
        TenantContext(tenant_slug="tenant-a"),
    )

    assert instructions == ()


def test_resolver_returns_empty_when_mapping_missing() -> None:
    resolver = DbProductMappingResolver()

    instructions = resolver.resolve(
        _event(
            (
                CanonicalLineItem(
                    external_product_id="prod_missing",
                    quantity=1,
                    amount_minor=1000,
                    currency="USD",
                ),
            )
        ),
        TenantContext(tenant_slug="tenant-a"),
    )

    assert instructions == ()

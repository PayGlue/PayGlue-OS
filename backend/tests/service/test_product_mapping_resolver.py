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


# PG-123: Patreon revoke-all -- a subscription.canceled event with no line
# items revokes every active mapping for that provider (Patreon's delete
# webhook doesn't carry the tier to target).


def _patreon_cancel_no_line_items() -> CanonicalPaymentEvent:
    return CanonicalPaymentEvent(
        provider="patreon",
        provider_event_id="evt_cancel_1",
        event_type="subscription.canceled",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        customer=CanonicalCustomer(email="patron@example.com", external_id="m_1"),
        line_items=(),
        status="canceled",
    )


def test_patreon_cancel_with_no_line_items_revokes_all_provider_mappings() -> None:
    ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="patreon",
        event_type="subscription.active",
        external_product_id="tier_gold",
        entitlement_key="tier.gold",
        action="grant",
        quantity=1,
        is_active=True,
    )
    ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="patreon",
        event_type="subscription.active",
        external_product_id="tier_silver",
        entitlement_key="tier.silver",
        action="grant",
        quantity=1,
        is_active=True,
    )
    resolver = DbProductMappingResolver()

    instructions = resolver.resolve(
        _patreon_cancel_no_line_items(), TenantContext(tenant_slug="tenant-a")
    )

    assert {i.entitlement_key for i in instructions} == {"tier.gold", "tier.silver"}
    assert all(i.action == "revoke" for i in instructions)


def test_patreon_cancel_all_dedupes_shared_entitlement_key() -> None:
    for tier in ("tier_a", "tier_b"):
        ProductMapping.objects.create(
            tenant_slug="tenant-a",
            payment_provider="patreon",
            event_type="subscription.active",
            external_product_id=tier,
            entitlement_key="tier.members",
            action="grant",
            quantity=1,
            is_active=True,
        )
    resolver = DbProductMappingResolver()

    instructions = resolver.resolve(
        _patreon_cancel_no_line_items(), TenantContext(tenant_slug="tenant-a")
    )

    assert len(instructions) == 1
    assert instructions[0].entitlement_key == "tier.members"
    assert instructions[0].action == "revoke"


def test_patreon_cancel_all_ignores_other_providers_and_inactive_mappings() -> None:
    ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="polar",
        event_type="order.paid",
        external_product_id="prod_x",
        entitlement_key="tier.polar",
        action="grant",
        quantity=1,
        is_active=True,
    )
    ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="patreon",
        event_type="subscription.active",
        external_product_id="tier_inactive",
        entitlement_key="tier.inactive",
        action="grant",
        quantity=1,
        is_active=False,
    )
    ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="patreon",
        event_type="subscription.active",
        external_product_id="tier_live",
        entitlement_key="tier.live",
        action="grant",
        quantity=1,
        is_active=True,
    )
    resolver = DbProductMappingResolver()

    instructions = resolver.resolve(
        _patreon_cancel_no_line_items(), TenantContext(tenant_slug="tenant-a")
    )

    assert {i.entitlement_key for i in instructions} == {"tier.live"}

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


def test_a_purchase_produces_one_instruction_even_if_the_table_holds_two_rules() -> None:
    """PG-254. The state this guards against cannot be created through the ORM
    any more, because the unique constraint refuses it, so the rows go in with
    the constraint lifted. That is the point: this is the belt to its braces,
    for a row written before the migration or restored from an older backup.

    Before, a buy button wrote the key `button` and a pricing tier wrote
    `product-<id>` for the same product. A purchase applied both, in id order,
    and the second one decided the member's newsletter flag and labels.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE webhooks_productmapping "
            "DROP CONSTRAINT webhooks_unique_product_mapping_rule"
        )
    common = {
        "tenant_slug": "tenant-a",
        "payment_provider": "polar",
        "event_type": "order.paid",
        "external_product_id": "prod_shared",
        "action": "grant",
        "quantity": 1,
        "is_active": True,
    }
    ProductMapping.objects.create(
        **common, entitlement_key="button", metadata={"ghost_subscribed": True}
    )
    ProductMapping.objects.create(
        **common, entitlement_key="product-prod_shared", metadata={"ghost_subscribed": False}
    )

    instructions = DbProductMappingResolver().resolve(
        _event(
            (
                CanonicalLineItem(
                    external_product_id="prod_shared",
                    quantity=1,
                    amount_minor=1000,
                    currency="EUR",
                ),
            )
        ),
        TenantContext(tenant_slug="tenant-a"),
    )

    assert len(instructions) == 1
    assert instructions[0].entitlement_key == "button"


def test_two_different_products_in_one_order_still_produce_two_instructions() -> None:
    """The dedupe is per product, not per order. Somebody buying a bundle of two
    products has to be granted both."""
    for product, key in (("prod_a", "tier.a"), ("prod_b", "tier.b")):
        ProductMapping.objects.create(
            tenant_slug="tenant-a",
            payment_provider="polar",
            event_type="order.paid",
            external_product_id=product,
            entitlement_key=key,
            action="grant",
            quantity=1,
            is_active=True,
        )

    instructions = DbProductMappingResolver().resolve(
        _event(
            (
                CanonicalLineItem(
                    external_product_id="prod_a", quantity=1, amount_minor=100, currency="EUR"
                ),
                CanonicalLineItem(
                    external_product_id="prod_b", quantity=1, amount_minor=200, currency="EUR"
                ),
            )
        ),
        TenantContext(tenant_slug="tenant-a"),
    )

    assert {i.entitlement_key for i in instructions} == {"tier.a", "tier.b"}


# --- PG-257: purchase and ending as classes, not as exact words -------------


def _typed_event(event_type: str, product: str = "prod_basic") -> CanonicalPaymentEvent:
    return CanonicalPaymentEvent(
        provider="polar",
        provider_event_id=f"evt_{event_type}",
        event_type=event_type,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        customer=CanonicalCustomer(email="x@example.com", external_id="cus_1"),
        line_items=(
            CanonicalLineItem(
                external_product_id=product,
                quantity=1,
                amount_minor=1000,
                currency="USD",
            ),
        ),
        status="paid",
    )


def _grant_rule(event_type: str = "order.paid", product: str = "prod_basic") -> ProductMapping:
    return ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="polar",
        event_type=event_type,
        external_product_id=product,
        entitlement_key="tier.basic",
        action="grant",
        quantity=1,
        is_active=True,
    )


@pytest.mark.parametrize("stored", ["order.paid", "subscription.active"])
@pytest.mark.parametrize("arrives", ["order.paid", "subscription.active"])
def test_a_purchase_grants_whichever_word_the_rule_carries(stored: str, arrives: str) -> None:
    """The one that cost readers their access. No widget ever sent the field,
    so every rule the dashboard writes says order.paid, and a provider that
    announces a subscription with subscription.active matched nothing at all.
    The purchase went through and the reader got no label."""
    _grant_rule(event_type=stored)

    instructions = DbProductMappingResolver().resolve(
        _typed_event(arrives), TenantContext(tenant_slug="tenant-a")
    )

    assert [(i.entitlement_key, i.action) for i in instructions] == [("tier.basic", "grant")]


@pytest.mark.parametrize("ending", ["subscription.canceled", "subscription.revoked"])
def test_an_ending_revokes_even_without_a_rule_of_its_own(ending: str) -> None:
    """subscription.revoked appeared in neither this resolver nor any test,
    while Lemon Squeezy, PayPal and Gumroad all emit it for the ordinary end of
    a subscription. Access was withdrawn on an active cancellation and never on
    an expiry, so the reader kept a label they no longer paid for."""
    _grant_rule()

    instructions = DbProductMappingResolver().resolve(
        _typed_event(ending), TenantContext(tenant_slug="tenant-a")
    )

    assert [(i.entitlement_key, i.action) for i in instructions] == [("tier.basic", "revoke")]


@pytest.mark.parametrize("ending", ["subscription.canceled", "subscription.revoked"])
def test_an_ending_never_grants(ending: str) -> None:
    """The line that must not break while widening the purchase class: a rule
    stored as a purchase must never be applied as written to an ending."""
    _grant_rule()

    instructions = DbProductMappingResolver().resolve(
        _typed_event(ending), TenantContext(tenant_slug="tenant-a")
    )

    assert all(i.action == "revoke" for i in instructions)


def test_an_explicit_ending_rule_wins_and_the_fallback_stays_out() -> None:
    """With a rule of its own the fallback must not fire on top, or the member
    would be answered twice for one event."""
    _grant_rule()
    ProductMapping.objects.create(
        tenant_slug="tenant-a",
        payment_provider="polar",
        event_type="subscription.canceled",
        external_product_id="prod_basic",
        entitlement_key="tier.basic",
        action="revoke",
        quantity=1,
        is_active=True,
    )

    instructions = DbProductMappingResolver().resolve(
        _typed_event("subscription.canceled"), TenantContext(tenant_slug="tenant-a")
    )

    assert len(instructions) == 1
    assert instructions[0].action == "revoke"


def test_an_unrelated_event_still_matches_exactly() -> None:
    """Only the two classes were widened. Everything else keeps the old
    behaviour, so a word we have no opinion about cannot pick up a grant."""
    _grant_rule()

    instructions = DbProductMappingResolver().resolve(
        _typed_event("subscription.paused"), TenantContext(tenant_slug="tenant-a")
    )

    assert instructions == ()


def test_a_purchase_does_not_reach_across_products() -> None:
    """Widening the type must not widen the product."""
    _grant_rule(product="prod_basic")

    instructions = DbProductMappingResolver().resolve(
        _typed_event("subscription.active", product="prod_other"),
        TenantContext(tenant_slug="tenant-a"),
    )

    assert instructions == ()

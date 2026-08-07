"""PG-233: the migration that takes the tier position out of the entitlement key.

The rewrite is exercised against the real model rather than through the
migration runner, because what has to hold is a property of the data: after the
rewrite no two rows collide on the unique constraint, and every pricing-table
mapping is keyed on its product instead of its position.
"""

import importlib

import pytest

from payglue_backend.webhooks.models import ProductMapping

# The module name starts with a digit, so it cannot be imported with a plain
# import statement.
migration_module = importlib.import_module(
    "payglue_backend.webhooks.migrations.0021_stable_entitlement_key"
)

pytestmark = pytest.mark.django_db


def _mapping(**overrides) -> ProductMapping:
    defaults = {
        "tenant_slug": "acme",
        "payment_provider": "polar",
        "event_type": "order.paid",
        "external_product_id": "prod_a",
        "entitlement_key": "pricing-tier-1",
        "action": "grant",
        "quantity": 1,
        "is_active": True,
        "metadata": {},
    }
    defaults.update(overrides)
    return ProductMapping.objects.create(**defaults)


def _run() -> None:
    """Call the migration body with the real app registry."""
    from django.apps import apps

    migration_module.forwards(apps, None)


def test_positional_key_becomes_product_derived() -> None:
    row = _mapping(entitlement_key="pricing-tier-2", external_product_id="prod_x")

    _run()

    row.refresh_from_db()
    assert row.entitlement_key == "product-prod_x"


def test_two_tiers_on_the_same_product_collapse_to_one() -> None:
    # A table with two tiers pointing at the same product produced two rows
    # that granted the same thing. Keyed on the product they become one, and
    # the oldest survives.
    first = _mapping(entitlement_key="pricing-tier-1")
    second = _mapping(entitlement_key="pricing-tier-2")

    _run()

    first.refresh_from_db()
    assert first.entitlement_key == "product-prod_a"
    assert not ProductMapping.objects.filter(id=second.id).exists()
    assert ProductMapping.objects.count() == 1


def test_different_products_stay_separate() -> None:
    _mapping(entitlement_key="pricing-tier-1", external_product_id="prod_a")
    _mapping(entitlement_key="pricing-tier-2", external_product_id="prod_b")

    _run()

    assert set(ProductMapping.objects.values_list("entitlement_key", flat=True)) == {
        "product-prod_a",
        "product-prod_b",
    }


def test_button_and_paywall_keys_are_left_alone() -> None:
    button = _mapping(entitlement_key="button")
    paywall = _mapping(entitlement_key="paywall")

    _run()

    button.refresh_from_db()
    paywall.refresh_from_db()
    assert button.entitlement_key == "button"
    assert paywall.entitlement_key == "paywall"


def test_a_tier_key_does_not_swallow_an_existing_product_key() -> None:
    # If a row already carries the target key, the legacy duplicate goes rather
    # than overwriting it, otherwise the constraint would reject the save.
    existing = _mapping(entitlement_key="product-prod_a")
    legacy = _mapping(entitlement_key="pricing-tier-3")

    _run()

    existing.refresh_from_db()
    assert existing.entitlement_key == "product-prod_a"
    assert not ProductMapping.objects.filter(id=legacy.id).exists()


def test_rows_of_other_tenants_do_not_collide() -> None:
    # The constraint is per tenant, so the same product in two tenants keeps
    # two rows.
    _mapping(tenant_slug="acme", entitlement_key="pricing-tier-1")
    _mapping(tenant_slug="globex", entitlement_key="pricing-tier-1")

    _run()

    assert ProductMapping.objects.count() == 2
    assert set(ProductMapping.objects.values_list("entitlement_key", flat=True)) == {
        "product-prod_a"
    }


def test_a_legacy_row_without_a_product_is_untouched() -> None:
    orphan = _mapping(entitlement_key="pricing-tier-1", external_product_id="")

    _run()

    orphan.refresh_from_db()
    assert orphan.entitlement_key == "pricing-tier-1"


def test_running_twice_changes_nothing() -> None:
    _mapping(entitlement_key="pricing-tier-1")

    _run()
    _run()

    assert ProductMapping.objects.count() == 1
    assert ProductMapping.objects.get().entitlement_key == "product-prod_a"

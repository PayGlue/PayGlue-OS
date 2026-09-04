# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-254: the merge that runs before the narrower unique constraint goes on.

Exercised against the real model, like the PG-233 migration test next door. The
property that has to hold is about the data: after the merge, no two rows share
the five fields the new constraint spans, which is the same as saying the
constraint can be added at all.

To get into the "before" state these tests have to drop the constraint first,
because the test database already has it. That is not a trick to get around the
rule; re-adding it at the end is the actual assertion.
"""

import importlib

import pytest
from django.db import IntegrityError, connection
from django.utils import timezone

from payglue_backend.webhooks.models import ProductMapping

# The module name starts with a digit, so a plain import statement will not do.
migration_module = importlib.import_module(
    "payglue_backend.webhooks.migrations.0022_product_mapping_one_row_per_product"
)

CONSTRAINT = "webhooks_unique_product_mapping_rule"
NEW_FIELDS = "tenant_slug, payment_provider, event_type, external_product_id, action"

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def without_the_constraint():
    """Drop it, hand back control, and put it back on the way out.

    Putting it back is what proves the merge did its job: on a table that still
    held two rows for one product, this would raise.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE webhooks_productmapping DROP CONSTRAINT {CONSTRAINT}")
    yield
    with connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE webhooks_productmapping "
            f"ADD CONSTRAINT {CONSTRAINT} UNIQUE ({NEW_FIELDS})"
        )


def _mapping(**overrides) -> ProductMapping:
    defaults = {
        "tenant_slug": "acme",
        "payment_provider": "polar",
        "event_type": "order.paid",
        "external_product_id": "prod_a",
        "entitlement_key": "button",
        "action": "grant",
        "quantity": 1,
        "is_active": True,
        "metadata": {},
    }
    defaults.update(overrides)
    return ProductMapping.objects.create(**defaults)


def _run() -> None:
    from django.apps import apps

    migration_module.merge_rows_that_would_collide(apps, None)


def test_a_button_and_a_tier_on_one_product_become_one_rule(without_the_constraint) -> None:
    """The case from the ticket. A buy button wrote `button`, a pricing tier
    wrote `product-<id>`, and a purchase applied both."""
    _mapping(entitlement_key="button")
    _mapping(entitlement_key="product-prod_a")

    _run()

    assert ProductMapping.objects.count() == 1


def test_the_row_saved_last_wins_not_the_oldest(without_the_constraint) -> None:
    """These rows are somebody's configuration. The last thing they saved is the
    best available guess at what they meant, so age is the wrong tiebreaker."""
    older = _mapping(entitlement_key="button", metadata={"ghost_subscribed": True})
    newer = _mapping(entitlement_key="product-prod_a", metadata={"ghost_subscribed": False})
    ProductMapping.objects.filter(pk=older.pk).update(
        updated_at=timezone.now() - timezone.timedelta(days=7)
    )

    _run()

    survivor = ProductMapping.objects.get()
    assert survivor.pk == newer.pk
    assert survivor.metadata == {"ghost_subscribed": False}


def test_rules_that_differ_in_any_constrained_field_are_left_alone(without_the_constraint) -> None:
    """The grant on a purchase and the revoke on a cancellation are two rules for
    one product, and both are needed. Same for a second product, or a second
    tenant that happens to sell the same thing."""
    _mapping(action="grant", event_type="order.paid")
    _mapping(action="revoke", event_type="subscription.canceled")
    _mapping(external_product_id="prod_b")
    _mapping(tenant_slug="other-tenant")

    _run()

    assert ProductMapping.objects.count() == 4


def test_a_table_that_is_already_clean_is_not_touched(without_the_constraint) -> None:
    """What production looked like when this was written: nobody had ever created
    the colliding state, so the merge is a no-op there."""
    first = _mapping()
    second = _mapping(external_product_id="prod_b")

    _run()

    assert set(ProductMapping.objects.values_list("pk", flat=True)) == {first.pk, second.pk}


def test_three_rules_for_one_product_collapse_to_the_newest(without_the_constraint) -> None:
    """Button, paywall and tier could all point at the same product."""
    _mapping(entitlement_key="button")
    _mapping(entitlement_key="paywall")
    last = _mapping(entitlement_key="product-prod_a")

    _run()

    assert ProductMapping.objects.get().pk == last.pk


def test_the_constraint_stops_a_second_rule_for_the_same_product() -> None:
    """Without the fixture, so the constraint is in place. This is the point of
    the whole change: the state is refused by the database rather than avoided by
    whichever editor happens to be saving."""
    _mapping(entitlement_key="button")

    with pytest.raises(IntegrityError):
        _mapping(entitlement_key="product-prod_a")

"""PG-254: one row per product, so a purchase has one outcome.

A payment webhook carries a product, never a widget. `resolver.py` can only
filter on `external_product_id`, so "what happens when somebody buys this" is a
property of the product. `entitlement_key` was part of the unique constraint,
which meant the same product could hold several rows with several different sets
of Ghost settings: a buy button wrote `button`, a paywall wrote `paywall`, a
pricing tier wrote `product-<id>`.

Nobody noticed, because access comes from the `payglue-active` label and was
granted either way. What silently differed was the newsletter flag, the email
types and the labels, applied twice in id order with the later row winning.

Taking the key out of the constraint makes that state impossible in the database
rather than merely avoided by the application, so it holds for the Django admin
and for any script as well.

## The merge below

Production had zero colliding groups when this was written (21 mappings across
5 tenants, checked 2026-08-10), so `forwards` is a no-op there. It exists for
every other installation, and because a collision could still be created between
that check and the deploy.

Without it, `AddConstraint` would raise mid-deploy. That fails safely, nothing is
corrupted, but it fails at the worst possible moment and leaves somebody to sort
it out by hand under pressure. Merging deliberately here is the better trade.

The most recently updated row wins, not the oldest. These rows are a customer's
configuration, and the last thing they saved is the best available guess at what
they meant. The rows that lose are printed before they are deleted, so the choice
can be reviewed afterwards instead of being invisible.

Reversing restores the wider constraint, which is lossless. The merge is not
reversed: the rows are gone, and inventing replacements would recreate exactly
the ambiguity this removes.
"""

from django.db import migrations, models

# Everything the new constraint spans. Rows agreeing on all of these are the
# same rule and must collapse to one.
IDENTITY = (
    "tenant_slug",
    "payment_provider",
    "event_type",
    "external_product_id",
    "action",
)


def merge_rows_that_would_collide(apps, schema_editor):
    ProductMapping = apps.get_model("webhooks", "ProductMapping")

    groups: dict[tuple, list] = {}
    for mapping in ProductMapping.objects.all().order_by("id"):
        groups.setdefault(tuple(getattr(mapping, f) for f in IDENTITY), []).append(mapping)

    for identity, rows in groups.items():
        if len(rows) < 2:
            continue

        # updated_at is auto_now, so it is never null and orders by "last saved".
        # The id breaks a tie, which only happens if two rows were written in the
        # same instant.
        rows.sort(key=lambda m: (m.updated_at, m.id), reverse=True)
        winner, losers = rows[0], rows[1:]

        print(
            f"  PG-254: {identity} had {len(rows)} rules. "
            f"Keeping id={winner.id} (key={winner.entitlement_key!r}, "
            f"updated {winner.updated_at:%Y-%m-%d %H:%M})."
        )
        for loser in losers:
            print(
                f"    dropping id={loser.id} key={loser.entitlement_key!r} "
                f"metadata={loser.metadata!r}"
            )
            loser.delete()


def keep_the_merge(apps, schema_editor):
    """Deliberately empty. See the module docstring."""


class Migration(migrations.Migration):

    dependencies = [
        ("webhooks", "0021_stable_entitlement_key"),
    ]

    operations = [
        migrations.RunPython(merge_rows_that_would_collide, keep_the_merge),
        migrations.RemoveConstraint(
            model_name="productmapping",
            name="webhooks_unique_product_mapping_rule",
        ),
        migrations.AddConstraint(
            model_name="productmapping",
            constraint=models.UniqueConstraint(
                fields=("tenant_slug", "payment_provider", "event_type", "external_product_id", "action"),
                name="webhooks_unique_product_mapping_rule",
            ),
        ),
    ]

"""PG-233: take the tier position out of the entitlement key.

Pricing-table mappings were keyed `pricing-tier-<n>`, where n was the tier's
position in the editor. Reordering or deleting a tier moved the key onto a
different product: the old tier's mapping stayed behind under a key nothing
pointed at any more, and the tier that inherited the position collided with it
on the unique constraint. This rewrites the existing rows to the key the editor
writes from now on, which is derived from the product instead.

Two rows can collapse onto the same key here, if a table had two tiers pointing
at the same product under the same provider, event type and action. They granted
the same entitlement twice, and the resolver already skipped the second one
(resolver.py dedupes on entitlement_key). The oldest row wins and the rest are
deleted, so the constraint holds afterwards.

Note that the `product:<key>` labels already written to Ghost members keep the
old value. They are informational: nothing reads them, and access is decided by
`payglue-active` plus the member status (PG-229).
"""

from django.db import migrations

LEGACY_PREFIX = "pricing-tier-"


def entitlement_key_for_product(product_id: str) -> str:
    """Mirror of entitlementKeyForProduct in frontend/src/lib/mappingKeys.ts."""
    return f"product-{product_id.strip()}"


def forwards(apps, schema_editor):
    ProductMapping = apps.get_model("webhooks", "ProductMapping")

    legacy = ProductMapping.objects.filter(
        entitlement_key__startswith=LEGACY_PREFIX
    ).order_by("id")

    # Everything the constraint spans, minus the key we are about to rewrite.
    # Two legacy rows landing in the same bucket would collide, so only the
    # first one is kept.
    claimed: set[tuple] = set()
    for mapping in ProductMapping.objects.exclude(
        entitlement_key__startswith=LEGACY_PREFIX
    ).only(
        "tenant_slug",
        "payment_provider",
        "event_type",
        "external_product_id",
        "entitlement_key",
        "action",
    ):
        claimed.add(
            (
                mapping.tenant_slug,
                mapping.payment_provider,
                mapping.event_type,
                mapping.external_product_id,
                mapping.entitlement_key,
                mapping.action,
            )
        )

    doomed: list[int] = []
    for mapping in legacy:
        if not mapping.external_product_id:
            # No product means no key to derive. Leave it alone rather than
            # inventing one; it never resolved to anything either way.
            continue
        new_key = entitlement_key_for_product(mapping.external_product_id)
        bucket = (
            mapping.tenant_slug,
            mapping.payment_provider,
            mapping.event_type,
            mapping.external_product_id,
            new_key,
            mapping.action,
        )
        if bucket in claimed:
            doomed.append(mapping.id)
            continue
        claimed.add(bucket)
        mapping.entitlement_key = new_key
        mapping.save(update_fields=["entitlement_key"])

    if doomed:
        ProductMapping.objects.filter(id__in=doomed).delete()


def backwards(apps, schema_editor):
    """Deliberately a no-op.

    The position a tier had when the key was written is not recoverable, and
    guessing one would recreate the exact collisions this migration removes.
    Rolling back leaves the product-derived keys in place, which the resolver
    handles fine because it never interprets the key.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0020_pricingtier_product_id_pricingtier_product_provider"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

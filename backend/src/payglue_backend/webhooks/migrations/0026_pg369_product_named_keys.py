# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-369: rules that share `button` or `paywall` get a key per product.

The buy button and paywall editors sent the widget's name as the key, so every
product sold through a button reached Ghost as `product:button`. In a tenant
with one such rule that label still names exactly one product and stays. Where
several active rules of a tenant share it, each of them is renamed to
`product-<id>`, and the old key is kept in `legacy_entitlement_key` so an ending
still recognises members who bought under the old label.

Inactive rows of such a group are renamed too: saving a widget switches an
inactive rule back on, and it must not come back under the shared name.
"""

from django.db import migrations, models
from django.db.models import Count

WIDGET_KEYS = ("button", "paywall")


def rename_shared_keys(apps, schema_editor):
    ProductMapping = apps.get_model("webhooks", "ProductMapping")
    shared = (
        ProductMapping.objects.filter(is_active=True, entitlement_key__in=WIDGET_KEYS)
        .values("tenant_slug", "entitlement_key")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    for group in shared:
        for mapping in ProductMapping.objects.filter(
            tenant_slug=group["tenant_slug"], entitlement_key=group["entitlement_key"]
        ):
            mapping.legacy_entitlement_key = mapping.entitlement_key
            mapping.entitlement_key = f"product-{mapping.external_product_id.strip()}"
            mapping.save(update_fields=["entitlement_key", "legacy_entitlement_key"])


def restore_shared_keys(apps, schema_editor):
    ProductMapping = apps.get_model("webhooks", "ProductMapping")
    for mapping in ProductMapping.objects.exclude(legacy_entitlement_key=""):
        mapping.entitlement_key = mapping.legacy_entitlement_key
        mapping.legacy_entitlement_key = ""
        mapping.save(update_fields=["entitlement_key", "legacy_entitlement_key"])


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0025_pg326_delivery_alert"),
    ]

    operations = [
        migrations.AddField(
            model_name="productmapping",
            name="legacy_entitlement_key",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.RunPython(rename_shared_keys, restore_shared_keys),
    ]

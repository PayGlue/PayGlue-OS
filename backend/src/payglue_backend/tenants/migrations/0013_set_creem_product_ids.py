# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations


# Real Creem product IDs for the Solo/Studio/Agency plans (GOGU-138). Each
# product is bundled with its annual counterpart in Creem's dashboard, so
# the monthly product's hosted checkout page already offers the yearly
# toggle -- these IDs are for our own records / future API calls, not
# required for the checkout links themselves (see VITE_CREEM_CHECKOUT_*).
CREEM_PRODUCT_IDS = {
    "solo": {
        "creem_product_id": "prod_5gakgfxPfJZLelLZzZlK51",
        "creem_product_id_annual": "prod_1UhnY9TYMNxwIKdAaXaoxO",
    },
    "studio": {
        "creem_product_id": "prod_5RxmZWN6UPzrgj6yEGWg5Y",
        "creem_product_id_annual": "prod_2JupveMKT6H8etEPHkeNP2",
    },
    "agency": {
        "creem_product_id": "prod_2hXGxVA3EbbbAZjiKMtVOu",
        "creem_product_id_annual": "prod_TLfJKIymEEsLAIRmfOSRO",
    },
}


def set_product_ids(apps, schema_editor):
    Plan = apps.get_model("tenants", "Plan")
    for key, ids in CREEM_PRODUCT_IDS.items():
        Plan.objects.filter(key=key).update(**ids)


def clear_product_ids(apps, schema_editor):
    Plan = apps.get_model("tenants", "Plan")
    Plan.objects.filter(key__in=CREEM_PRODUCT_IDS.keys()).update(
        creem_product_id="", creem_product_id_annual=""
    )


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0012_seed_plans_and_backfill_billing_accounts'),
    ]

    operations = [
        migrations.RunPython(set_product_ids, clear_product_ids),
    ]

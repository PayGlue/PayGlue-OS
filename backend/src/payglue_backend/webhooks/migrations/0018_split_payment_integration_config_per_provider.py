# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations


def split_payment_slot_forwards(apps, schema_editor):
    """Each tenant previously shared a single IntegrationConfig row keyed
    provider_key="payment" for whichever payment provider was configured
    last. Credentials were always stored per-provider already
    (TenantProviderCredential keyed by provider_type), so this only
    renames the config row's provider_key to match its own provider_type
    -- no credentials move, no data is lost.
    """
    IntegrationConfig = apps.get_model("webhooks", "IntegrationConfig")
    for row in IntegrationConfig.objects.filter(provider_key="payment"):
        if not row.provider_type:
            continue
        row.provider_key = row.provider_type
        row.save(update_fields=["provider_key"])


def split_payment_slot_backwards(apps, schema_editor):
    IntegrationConfig = apps.get_model("webhooks", "IntegrationConfig")
    payment_provider_keys = {"polar", "lemonsqueezy", "paypal", "gumroad"}
    for row in IntegrationConfig.objects.filter(provider_key__in=payment_provider_keys):
        row.provider_key = "payment"
        row.save(update_fields=["provider_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("webhooks", "0017_pricingtable_currency"),
    ]

    operations = [
        migrations.RunPython(split_payment_slot_forwards, split_payment_slot_backwards),
    ]

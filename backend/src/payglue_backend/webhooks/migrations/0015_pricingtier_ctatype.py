# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


def rename_free_url_to_custom_url(apps, schema_editor):
    PricingTier = apps.get_model("webhooks", "PricingTier")
    PricingTier.objects.filter(cta_type="free_url").update(cta_type="custom_url")


class Migration(migrations.Migration):

    dependencies = [
        ("webhooks", "0014_pricingtable"),
    ]

    operations = [
        migrations.RunPython(rename_free_url_to_custom_url, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="pricingtier",
            name="cta_type",
            field=models.CharField(
                choices=[
                    ("custom_url", "custom_url"),
                    ("free_signup", "free_signup"),
                    ("one_time", "one_time"),
                    ("subscription", "subscription"),
                ],
                default="custom_url",
                max_length=16,
            ),
        ),
    ]

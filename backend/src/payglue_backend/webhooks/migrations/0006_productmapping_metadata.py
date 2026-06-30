# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0005_rename_webhooks_te_tenant__cred_idx_webhooks_te_tenant__9770a6_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="productmapping",
            name="metadata",
            field=models.JSONField(default=dict),
        ),
    ]

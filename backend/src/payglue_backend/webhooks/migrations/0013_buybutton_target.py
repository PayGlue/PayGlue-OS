# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("webhooks", "0012_paywallconfig_styling"),
    ]

    operations = [
        migrations.AddField(
            model_name="buybutton",
            name="target",
            field=models.CharField(
                choices=[("_blank", "_blank"), ("_self", "_self")],
                default="_blank",
                max_length=8,
            ),
        ),
    ]

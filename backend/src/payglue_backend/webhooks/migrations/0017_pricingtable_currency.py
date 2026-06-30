# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("webhooks", "0016_pricingtable_accent_color"),
    ]

    operations = [
        migrations.AddField(
            model_name="pricingtable",
            name="currency",
            field=models.CharField(default="EUR", max_length=3),
        ),
    ]

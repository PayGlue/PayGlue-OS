# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("webhooks", "0015_pricingtier_ctatype"),
    ]

    operations = [
        migrations.AddField(
            model_name="pricingtable",
            name="accent_color",
            field=models.CharField(default="#4f46e5", max_length=7),
        ),
    ]

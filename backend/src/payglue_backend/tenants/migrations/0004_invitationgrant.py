# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0003_billingprofile_publicauditevent"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvitationGrant",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("email", models.EmailField(max_length=254, unique=True)),
                (
                    "invitation_code_prefix",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                ("verified_at", models.DateTimeField(auto_now=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        )
    ]

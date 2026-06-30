# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("webhooks", "0013_buybutton_target"),
    ]

    operations = [
        migrations.CreateModel(
            name="PricingTable",
            fields=[
                ("id", models.CharField(max_length=32, primary_key=True, serialize=False)),
                ("tenant_slug", models.CharField(db_index=True, max_length=64)),
                ("name", models.CharField(max_length=255)),
                (
                    "template",
                    models.CharField(
                        choices=[("classic", "classic"), ("minimal", "minimal"), ("bold", "bold")],
                        default="classic",
                        max_length=16,
                    ),
                ),
                ("show_toggle", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["tenant_slug", "created_at"], name="webhooks_prt_tenant__idx")
                ],
            },
        ),
        migrations.CreateModel(
            name="PricingTier",
            fields=[
                ("id", models.CharField(max_length=32, primary_key=True, serialize=False)),
                (
                    "table",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tiers",
                        to="webhooks.pricingtable",
                    ),
                ),
                ("position", models.IntegerField(default=0)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                ("price_monthly", models.CharField(blank=True, default="", max_length=64)),
                ("price_yearly", models.CharField(blank=True, default="", max_length=64)),
                ("trial_days", models.IntegerField(blank=True, null=True)),
                ("highlight", models.BooleanField(default=False)),
                ("ribbon_text", models.CharField(blank=True, default="", max_length=10)),
                (
                    "cta_type",
                    models.CharField(
                        choices=[
                            ("free_url", "free_url"),
                            ("one_time", "one_time"),
                            ("subscription", "subscription"),
                        ],
                        default="free_url",
                        max_length=16,
                    ),
                ),
                ("cta_label", models.CharField(default="Get started", max_length=128)),
                ("cta_url", models.CharField(blank=True, default="", max_length=512)),
                ("features", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["position"],
            },
        ),
    ]

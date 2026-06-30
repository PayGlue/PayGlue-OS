# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list[tuple[str, str]] = []

    operations = [
        migrations.CreateModel(
            name="WebhookEventRecord",
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
                ("idempotency_key", models.CharField(max_length=255, unique=True)),
                ("tenant_slug", models.CharField(max_length=64)),
                ("provider", models.CharField(max_length=64)),
                ("provider_event_id", models.CharField(max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("processing", "processing"),
                            ("processed", "processed"),
                            ("released", "released"),
                        ],
                        max_length=16,
                    ),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddIndex(
            model_name="webhookeventrecord",
            index=models.Index(
                fields=["tenant_slug", "provider", "provider_event_id"],
                name="webhooks_we_tenant__3e49fe_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="webhookeventrecord",
            index=models.Index(fields=["status"], name="webhooks_we_status_77bc3e_idx"),
        ),
    ]

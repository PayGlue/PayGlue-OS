# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-326: the delivery alert gets its own table.

Copies every open incident out of the Ghost connection's metadata and removes
the key there, so the state has one home. An incident written by the pre-PG-319
command carries no timestamp; it is treated as "told just now", which is what
the nightly job did with it before.
"""

from django.db import migrations, models
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def _aware(value):
    moment = parse_datetime(value or "") if isinstance(value, str) else None
    if moment is None:
        return None
    return timezone.make_aware(moment) if timezone.is_naive(moment) else moment


def copy_state(apps, schema_editor):
    IntegrationConfig = apps.get_model("webhooks", "IntegrationConfig")
    DeliveryAlert = apps.get_model("webhooks", "DeliveryAlert")
    now = timezone.now()
    for config in IntegrationConfig.objects.filter(provider_key="cms"):
        metadata = config.metadata or {}
        if "delivery_alert" not in metadata:
            continue
        state = metadata.pop("delivery_alert") or {}
        if state.get("state") == "failing":
            notified_at = _aware(state.get("notified_at")) or now
            try:
                count = int(state.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            DeliveryAlert.objects.update_or_create(
                tenant_slug=config.tenant_slug,
                defaults={
                    "state": "failing",
                    "kind": str(state.get("kind") or "ghost")[:16],
                    "provider": str(state.get("provider") or "")[:64],
                    "failure_count": max(count, 0),
                    "failing_since": str(state.get("since") or "")[:32],
                    "first_failed_at": notified_at,
                    "notified_at": notified_at,
                    "escalated_at": _aware(state.get("escalated_at")),
                },
            )
        config.metadata = metadata
        config.save(update_fields=["metadata"])


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0024_pg322_pricing_tier_yearly_product"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeliveryAlert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_slug", models.CharField(max_length=64, unique=True)),
                ("state", models.CharField(choices=[("healthy", "healthy"), ("pending", "pending"), ("failing", "failing")], default="healthy", max_length=16)),
                ("kind", models.CharField(blank=True, default="", max_length=16)),
                ("provider", models.CharField(blank=True, default="", max_length=64)),
                ("failure_count", models.PositiveIntegerField(default=0)),
                ("failing_since", models.CharField(blank=True, default="", max_length=32)),
                ("first_failed_at", models.DateTimeField(blank=True, null=True)),
                ("notified_at", models.DateTimeField(blank=True, null=True)),
                ("escalated_at", models.DateTimeField(blank=True, null=True)),
                ("send_attempts", models.PositiveIntegerField(default=0)),
                ("last_send_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.RunPython(copy_state, migrations.RunPython.noop),
    ]

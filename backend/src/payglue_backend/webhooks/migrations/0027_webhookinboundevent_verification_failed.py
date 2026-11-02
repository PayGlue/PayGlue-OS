# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models

# What the adapters wrote into last_error for a delivery that could not be
# verified. Only needed once: from now on the worker records it on the row.
_UNVERIFIED = (
    r"signature|verification token|webhook secret|webhook headers|paypal oauth|paypal verify"
)


def mark_existing(apps, schema_editor) -> None:
    events = apps.get_model("webhooks", "WebhookInboundEvent")
    events.objects.filter(
        status__in=("failed", "dead_letter"), last_error__iregex=_UNVERIFIED
    ).update(verification_failed=True)


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0026_pg369_product_named_keys"),
    ]

    operations = [
        migrations.AddField(
            model_name="webhookinboundevent",
            name="verification_failed",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing, migrations.RunPython.noop),
    ]

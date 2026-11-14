# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations, models


def mark_existing(apps, schema_editor) -> None:
    # Only events that were applied or skipped on their first attempt are
    # known to have passed the check: the first attempt always verified. For
    # everything else the history cannot tell, so the field stays False and
    # a retry or a replay verifies again.
    events = apps.get_model("webhooks", "WebhookInboundEvent")
    events.objects.filter(
        status__in=("processed", "skipped"), attempts__lte=1, verification_failed=False
    ).update(signature_verified=True)


class Migration(migrations.Migration):
    dependencies = [
        ("webhooks", "0027_webhookinboundevent_verification_failed"),
    ]

    operations = [
        migrations.AddField(
            model_name="webhookinboundevent",
            name="signature_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing, migrations.RunPython.noop),
    ]

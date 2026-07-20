# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import secrets

from django.db import migrations, models

import payglue_backend.tenants.models


def backfill_webhook_secrets(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.all():
        tenant.webhook_secret = secrets.token_urlsafe(24)
        tenant.save(update_fields=["webhook_secret"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0005_add_access_redemption_and_invitation_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="webhook_secret",
            field=models.CharField(max_length=64, null=True, blank=True, default=None),
        ),
        migrations.RunPython(backfill_webhook_secrets, noop_reverse),
        migrations.AlterField(
            model_name="tenant",
            name="webhook_secret",
            field=models.CharField(
                max_length=64,
                unique=True,
                default=payglue_backend.tenants.models._generate_webhook_secret,
                help_text="Per-tenant secret embedded in this tenant's webhook URLs, replacing the old shared global endpoint token.",
            ),
        ),
    ]

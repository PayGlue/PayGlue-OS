# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-182: seed the owner_transfer_requested email template so its subject/body
are editable in Django Admin next to the other templates. Seeded ENABLED with
real copy (the confirmation mail is essential to the flow). Placeholders:
$email, $new_owner, $tenant, $url."""
from django.db import migrations

TRIGGER = "owner_transfer_requested"
SUBJECT = "PayGlue: Owner-Wechsel angefordert fuer $tenant"
BODY = (
    "Hi,\n\n"
    "fuer deine Publication $tenant wurde ein Owner-Wechsel zu $new_owner "
    "angefordert.\n\n"
    "Aus Sicherheitsgruenden wird der Wechsel erst wirksam, wenn du ihn selbst "
    "bestaetigst. Bitte logge dich in PayGlue ein und bestaetige oder lehne den "
    "Wechsel unter Team ab:\n$url\n\n"
    "Wenn du das nicht warst, lehne den Wechsel ab und pruefe, wer Zugriff auf "
    "deinen Account hat. Deine Abrechnung laeuft weiter ueber dich (du wirst "
    "nach der Bestaetigung Billing-Admin).\n\n"
    "Dein PayGlue-Team"
)


def seed(apps, schema_editor):
    LifecycleEmailTemplate = apps.get_model("tenants", "LifecycleEmailTemplate")
    LifecycleEmailTemplate.objects.get_or_create(
        trigger=TRIGGER,
        defaults={"subject": SUBJECT, "body": BODY, "enabled": True},
    )


def unseed(apps, schema_editor):
    LifecycleEmailTemplate = apps.get_model("tenants", "LifecycleEmailTemplate")
    LifecycleEmailTemplate.objects.filter(trigger=TRIGGER).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0023_alter_lifecycleemaillog_trigger_and_more"),
    ]

    operations = [migrations.RunPython(seed, unseed)]

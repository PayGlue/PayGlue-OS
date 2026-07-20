# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-192: seed the ghost_delivery_failing email template so André can edit its
subject/body in Django Admin alongside the subscription lifecycle templates.

Unlike the subscription placeholder templates (seeded disabled in 0017/0019,
"nothing sends until reviewed"), this one is seeded ENABLED with real copy: the
alert is the whole point of PG-192 and should work out of the box. Placeholders:
$email, $tenant, $url."""
from django.db import migrations

TRIGGER = "ghost_delivery_failing"
SUBJECT = "PayGlue: Deine Ghost-Verbindung schlaegt gerade fehl"
BODY = (
    "Hi,\n\n"
    "die Zugriffs-Freischaltung an dein Ghost ($tenant) schlaegt gerade "
    "wiederholt fehl. Das heisst: neue Kaeufe werden aktuell NICHT automatisch "
    "freigeschaltet.\n\n"
    "Haeufigste Ursache: dein Ghost-Admin-API-Key wurde rotiert oder ist "
    "abgelaufen, oder deine Ghost-Instanz ist gerade nicht erreichbar.\n\n"
    "Bitte pruefe die Ghost-Verbindung in PayGlue:\n"
    "$url\n\n"
    "Dort kannst du deine Ghost-Zugangsdaten aktualisieren und mit 'Run health "
    "check' testen. Sobald die Verbindung wieder laeuft, werden ausstehende "
    "Events automatisch erneut zugestellt.\n\n"
    "Dein PayGlue-Team"
)


def seed_template(apps, schema_editor):
    LifecycleEmailTemplate = apps.get_model("tenants", "LifecycleEmailTemplate")
    LifecycleEmailTemplate.objects.get_or_create(
        trigger=TRIGGER,
        defaults={"subject": SUBJECT, "body": BODY, "enabled": True},
    )


def remove_template(apps, schema_editor):
    LifecycleEmailTemplate = apps.get_model("tenants", "LifecycleEmailTemplate")
    LifecycleEmailTemplate.objects.filter(trigger=TRIGGER).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0021_alter_lifecycleemaillog_trigger_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_template, remove_template),
    ]

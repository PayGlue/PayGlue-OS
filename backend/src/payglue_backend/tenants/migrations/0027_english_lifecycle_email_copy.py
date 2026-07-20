# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-202: the owner_transfer_requested and ghost_delivery_failing templates were
seeded in German. PayGlue's product language is English, so rewrite the two
customer-facing rows. Only touches rows still holding the exact German seed copy
-- if André already edited one in the admin, his version is left untouched."""
from django.db import migrations

_GERMAN_OWNER_SUBJECT = "PayGlue: Owner-Wechsel angefordert fuer $tenant"
_GERMAN_GHOST_SUBJECT = "PayGlue: Deine Ghost-Verbindung schlaegt gerade fehl"

_OWNER_SUBJECT = "PayGlue: Ownership transfer requested for $tenant"
_OWNER_BODY = (
    "Hi,\n\n"
    "Someone requested to transfer ownership of your publication $tenant to "
    "$new_owner.\n\n"
    "For security, the transfer only takes effect once you confirm it yourself. "
    "Please log in to PayGlue and confirm or reject it under Team:\n$url\n\n"
    "If this wasn't you, reject the transfer and check who has access to your "
    "account. Your billing stays with you -- after you confirm, you become the "
    "billing admin.\n\n"
    "Thanks,\nThe PayGlue Team"
)
_GHOST_SUBJECT = "PayGlue: Your Ghost connection is failing"
_GHOST_BODY = (
    "Hi,\n\n"
    "Access delivery to your Ghost site ($tenant) has been failing repeatedly. "
    "That means new purchases are NOT being unlocked automatically right now.\n\n"
    "Most common cause: your Ghost Admin API key was rotated or has expired, or "
    "your Ghost instance is temporarily unreachable.\n\n"
    "Please check your Ghost connection in PayGlue:\n"
    "$url\n\n"
    "There you can update your Ghost credentials and re-test with 'Run health "
    "check'. Once the connection works again, pending events are re-delivered "
    "automatically.\n\n"
    "Thanks,\nThe PayGlue Team"
)


def to_english(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    # Match on the German subject so a template André already re-worded is skipped.
    Template.objects.filter(
        trigger="owner_transfer_requested", subject=_GERMAN_OWNER_SUBJECT
    ).update(subject=_OWNER_SUBJECT, body=_OWNER_BODY)
    Template.objects.filter(
        trigger="ghost_delivery_failing", subject=_GERMAN_GHOST_SUBJECT
    ).update(subject=_GHOST_SUBJECT, body=_GHOST_BODY)


def noop(apps, schema_editor):
    # No down-migration: we don't want to reintroduce German copy.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0026_invitationgrant_creem_license_instance_id"),
    ]

    operations = [migrations.RunPython(to_english, noop)]

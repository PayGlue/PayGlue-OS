# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-182 follow-up: seed the three missing ownership-transfer emails so they're
editable in Django Admin next to the existing one, and unify the sign-off across
every seeded template.

Seeded ENABLED: unlike the subscription templates (placeholder copy, off until
reviewed) these are transactional -- a proposed owner who never hears about the
nomination is the exact gap this fixes, so shipping them off would be pointless.

The sign-off pass only rewrites rows that still hold the exact seeded copy, the
same guard 0027 used: anything André already edited in the admin is his and
stays untouched.
"""
from django.db import migrations

_SIGN_OFF = "__\nCheers,\nPayGlue - Team"

NEW_TEMPLATES = [
    {
        "trigger": "owner_transfer_proposed",
        "subject": "PayGlue: You've been proposed as the owner of $tenant",
        "body": (
            "Hi,\n\n"
            "You've been proposed as the new owner of the publication $tenant.\n\n"
            "Nothing has changed yet. $previous_owner still has to confirm the transfer, "
            "and you'll get another email as soon as that happens.\n\n"
            "As the owner you would manage the team and the publication itself. Billing "
            "stays with $previous_owner, so nothing about the subscription moves to you.\n\n"
            "You can follow the status here:\n$url\n\n" + _SIGN_OFF
        ),
    },
    {
        "trigger": "owner_transfer_confirmed",
        "subject": "PayGlue: $new_owner is now the owner of $tenant",
        "body": (
            "Hi,\n\n"
            "The ownership transfer for $tenant is complete. $new_owner is now the owner.\n\n"
            "$previous_owner keeps access as billing admin, so the subscription and all "
            "invoices stay exactly where they were.\n\n"
            "You can review the team here:\n$url\n\n"
            "If you weren't expecting this change, reply to this email right away.\n\n"
            + _SIGN_OFF
        ),
    },
    {
        "trigger": "owner_transfer_rejected",
        "subject": "PayGlue: The ownership transfer for $tenant was called off",
        "body": (
            "Hi,\n\n"
            "The requested ownership transfer of $tenant to $new_owner will not go ahead. "
            "It was either rejected by the current owner or cancelled before it was "
            "confirmed.\n\n"
            "Nothing changed. $previous_owner is still the owner and every role stayed as "
            "it was.\n\n"
            "You can review the team here:\n$url\n\n" + _SIGN_OFF
        ),
    },
]

# Old closings, exactly as seeded by 0017 / 0019 / 0027. Anything else means the
# row was hand-edited, so we leave it alone.
_OLD_SIGN_OFFS = ["-- PayGlue", "Thanks,\nThe PayGlue Team"]


def seed(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    for row in NEW_TEMPLATES:
        Template.objects.get_or_create(
            trigger=row["trigger"],
            defaults={"subject": row["subject"], "body": row["body"], "enabled": True},
        )

    for template in Template.objects.all():
        for old in _OLD_SIGN_OFFS:
            if template.body.endswith(old):
                template.body = template.body[: -len(old)] + _SIGN_OFF
                template.save(update_fields=["body"])
                break


def unseed(apps, schema_editor):
    # Only the new rows are reversible; the sign-off rewrite is not worth
    # undoing (and we have no record of which rows we touched).
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    Template.objects.filter(trigger__in=[r["trigger"] for r in NEW_TEMPLATES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0027_english_lifecycle_email_copy"),
    ]

    operations = [migrations.RunPython(seed, unseed)]

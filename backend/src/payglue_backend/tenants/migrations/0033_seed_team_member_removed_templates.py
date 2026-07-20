# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Seed the two team-member-removal emails so they show up in Django Admin.

PG-210 shipped them with built-in fallback copy only, which works but leaves
André unable to see or edit the wording anywhere -- the admin list showed ten
templates and no sign these two existed. Every other transactional email is
editable there, so these are too.

Seeded ENABLED, like the ownership-transfer templates and unlike the
subscription ones: an access change nobody is told about is the gap this
closes, so shipping them switched off would defeat the point.
"""
from django.db import migrations

_SIGN_OFF = "__\nCheers,\nPayGlue - Team"

NEW_TEMPLATES = [
    {
        "trigger": "team_member_removed",
        "subject": "You were removed from $tenant on PayGlue",
        "body": (
            "Hi,\n\n"
            "$actor removed your access to the publication \"$tenant\" on PayGlue.\n\n"
            "You can no longer see its connections, paywalls or events. Any other "
            "publications you belong to are unaffected, and your PayGlue account "
            "itself still exists.\n\n"
            "If you did not expect this, contact whoever runs that publication. "
            "We cannot restore access on their behalf.\n\n" + _SIGN_OFF
        ),
    },
    {
        "trigger": "team_member_removed_notice",
        "subject": "$member was removed from $tenant",
        "body": (
            "Hi,\n\n"
            "$actor removed $member ($role) from the publication \"$tenant\" on "
            "PayGlue.\n\n"
            "You are getting this because you are responsible for that "
            "publication. If this was not expected, review your team now:\n\n"
            "$url\n\n"
            "Every role change is also recorded in the publication's audit log.\n\n"
            + _SIGN_OFF
        ),
    },
]


def seed(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    for row in NEW_TEMPLATES:
        Template.objects.get_or_create(
            trigger=row["trigger"],
            defaults={"subject": row["subject"], "body": row["body"], "enabled": True},
        )


def unseed(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    Template.objects.filter(trigger__in=[r["trigger"] for r in NEW_TEMPLATES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0032_alter_lifecycleemaillog_trigger_and_more"),
    ]

    operations = [migrations.RunPython(seed, unseed)]

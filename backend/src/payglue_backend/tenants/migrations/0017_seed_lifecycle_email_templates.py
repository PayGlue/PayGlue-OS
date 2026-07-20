# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-148: seeds the 3 fixed trigger rows so they exist to edit in Django
Admin (the admin intentionally disallows adding/deleting rows, only fixed
choices from LifecycleEmailTemplate.Trigger). Disabled by default -- these
are placeholder copy, nothing should send until André reviews and turns
each one on."""
from django.db import migrations

PLACEHOLDER_TEMPLATES = [
    {
        "trigger": "downgrade",
        "subject": "Sorry to see you downgrade, $email",
        "body": (
            "Hi,\n\nWe noticed you just downgraded to the $plan plan. "
            "Was something not working for you, or was it just a fit thing? "
            "Reply to this email and let us know -- we read every one.\n\n"
            "-- PayGlue"
        ),
    },
    {
        "trigger": "scheduled_cancellation",
        "subject": "Your PayGlue subscription is set to end",
        "body": (
            "Hi,\n\nYour $plan subscription is scheduled to end. You'll still have full access "
            "until then. If there's anything we can do to change your mind, just reply here.\n\n"
            "-- PayGlue"
        ),
    },
    {
        "trigger": "subscription_ended",
        "subject": "Your PayGlue subscription has ended",
        "body": (
            "Hi,\n\nYour PayGlue subscription has ended. Your account and any paused workspaces "
            "are still there if you ever want to come back.\n\n"
            "-- PayGlue"
        ),
    },
]


def seed_templates(apps, schema_editor):
    LifecycleEmailTemplate = apps.get_model("tenants", "LifecycleEmailTemplate")
    for row in PLACEHOLDER_TEMPLATES:
        LifecycleEmailTemplate.objects.get_or_create(
            trigger=row["trigger"],
            defaults={"subject": row["subject"], "body": row["body"], "enabled": False},
        )


def remove_templates(apps, schema_editor):
    LifecycleEmailTemplate = apps.get_model("tenants", "LifecycleEmailTemplate")
    LifecycleEmailTemplate.objects.filter(
        trigger__in=[row["trigger"] for row in PLACEHOLDER_TEMPLATES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0016_lifecycleemailtemplate_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_templates, remove_templates),
    ]

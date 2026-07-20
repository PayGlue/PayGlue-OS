# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-190: seeds the 2 new grace-period reminder triggers so they exist to
edit in Django Admin (same reasoning as 0017 -- the admin intentionally
disallows adding/deleting rows, only fixed choices from
LifecycleEmailTemplate.Trigger). Disabled by default -- placeholder copy,
nothing should send until André reviews and turns each one on. The day-1
notice itself reuses the existing SUBSCRIPTION_ENDED template (seeded in
0017), no new trigger needed for that one."""
from django.db import migrations

PLACEHOLDER_TEMPLATES = [
    {
        "trigger": "cancellation_reminder_15d",
        "subject": "15 days left on your PayGlue grace period",
        "body": (
            "Hi,\n\nYour PayGlue subscription ended 15 days ago. You've got 15 more days "
            "before your account and workspaces are permanently deleted. If you'd like to "
            "keep everything, just resubscribe from your dashboard -- no data has been lost yet.\n\n"
            "-- PayGlue"
        ),
    },
    {
        "trigger": "cancellation_final_warning",
        "subject": "Your PayGlue account will be deleted tomorrow",
        "body": (
            "Hi,\n\nThis is the last reminder: your PayGlue account and all its workspaces "
            "will be permanently deleted tomorrow, 30 days after your subscription ended. "
            "Resubscribe from your dashboard now if you want to keep everything.\n\n"
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
        ('tenants', '0018_pg190_cancellation_and_review_fields'),
    ]

    operations = [
        migrations.RunPython(seed_templates, remove_templates),
    ]

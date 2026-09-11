# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-303: seed the two emails at the end of the lapse process.

deletion_notice goes out a week before a paused account is deleted, and the
deletion refuses to run until it has. inactive_account_deleted is the
receipt afterwards; it is not the self-service account_deleted template,
whose copy confirms something the owner asked for.

Seeded disabled, like the lapse templates before them: nothing reaches a
customer until whoever runs the installation has read the wording and
turned it on. No links and no addresses in the copy, every installation runs
on its own domain.
"""
from django.db import migrations

# Repeated rather than imported: a migration has to keep saying what it said
# the day it ran, so it must not follow a constant that runtime code may
# reword.
_SIGN_OFF = "__\nCheers,\nPayGlue - Team"

TEMPLATES = [
    {
        "trigger": "deletion_notice",
        "subject": "Your PayGlue account is scheduled for deletion on $deletion_date",
        "body": (
            "Hey,\n\n"
            "your PayGlue workspaces have been paused for almost three months now, "
            "since your subscription ended. On $deletion_date we will delete the "
            "account: your profile, the publications you own, their connections, "
            "mappings, paywalls, buttons and webhook history, along with your "
            "sign-in.\n\n"
            "If you want to keep it, that takes a minute: sign in to your "
            "dashboard and pick a plan. Everything is still there exactly as you "
            "left it, and purchases at your payment provider unlock Ghost access "
            "again the moment the plan is active. No setup to redo.\n\n"
            "If you are done with PayGlue, you do not need to do anything. Your "
            "Ghost site and your members are not affected either way; access "
            "lives in Ghost, not with us. Invoices stay with our payment provider, "
            "who has to keep them for the statutory period.\n\n"
            "If you have questions, reply to this email.\n\n" + _SIGN_OFF
        ),
    },
    {
        "trigger": "inactive_account_deleted",
        "subject": "Your PayGlue account has been deleted",
        "body": (
            "Hi,\n\n"
            "your PayGlue account has been deleted. Your subscription ended, the "
            "workspaces were paused for three months without a new plan, and we "
            "let you know a week ago that this was coming.\n\n"
            "This has already happened: your profile, the publications you solely "
            "owned, their connections, paywalls, buy buttons, pricing tables, "
            "product mappings, stored provider credentials and webhook history "
            "were removed from our servers, along with your sign-in account.\n\n"
            "Your Ghost site is untouched. Member access lives in your own Ghost "
            "instance, not in PayGlue, so nobody loses access because this account "
            "is gone.\n\n"
            "Invoices and payment records are the one exception. They sit with our "
            "payment provider, who is required to keep them for the statutory "
            "period (GDPR Article 17(3)(b)). We hold no copy.\n\n"
            "If you want to come back, sign up again and set things up fresh. We "
            "would be glad to have you.\n\n" + _SIGN_OFF
        ),
    },
]


def seed(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    for row in TEMPLATES:
        Template.objects.get_or_create(
            trigger=row["trigger"],
            defaults={"subject": row["subject"], "body": row["body"], "enabled": False},
        )


def unseed(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    Template.objects.filter(trigger__in=[r["trigger"] for r in TEMPLATES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0054_pg303_deletion_triggers"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

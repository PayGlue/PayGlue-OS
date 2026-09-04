# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-298: seed the three emails of the lapse process.

payment_failed and payment_failed_reminder go out while the payment provider
is still retrying the card, before any grace period exists. access_paused is
the notice at the end of the grace period, replacing the deletion that
delete_lapsed_accounts used to carry out.

Seeded disabled, like every template before it: nothing reaches a customer
until whoever runs the installation has read the wording and turned it on.
The copy carries no links and no addresses on purpose, every installation
runs on its own domain.
"""
from django.db import migrations

# Repeated rather than imported: a migration has to keep saying what it said
# the day it ran, so it must not follow a constant that runtime code may
# reword.
_SIGN_OFF = "__\nCheers,\nPayGlue - Team"

TEMPLATES = [
    {
        "trigger": "payment_failed",
        "subject": "We could not charge your card for PayGlue",
        "body": (
            "Hey,\n\n"
            "the last payment for your PayGlue plan ($plan) did not go through. "
            "Cards expire, banks block things, it happens.\n\n"
            "Your payment provider will retry over the next few days. To make sure "
            "the retry works, please check the card on file: open Billing in your "
            "dashboard and update the payment method there.\n\n"
            "Nothing changes on your side for now. Your workspaces keep running "
            "and your Ghost members keep their access.\n\n"
            "If you think this is a mistake, just reply to this email.\n\n" + _SIGN_OFF
        ),
    },
    {
        "trigger": "payment_failed_reminder",
        "subject": "Still no luck charging your card",
        "body": (
            "Hey,\n\n"
            "a few days ago we let you know that the payment for your PayGlue plan "
            "($plan) failed. The retries have not gone through yet either.\n\n"
            "Please take a minute to update the card: open Billing in your "
            "dashboard and change the payment method there. Once a retry "
            "succeeds, everything continues as before.\n\n"
            "If the retries keep failing, your subscription ends and a 30-day "
            "grace period starts. We will let you know when that happens.\n\n"
            + _SIGN_OFF
        ),
    },
    {
        "trigger": "access_paused",
        "subject": "Your PayGlue workspaces are paused",
        "body": (
            "Hey,\n\n"
            "the 30-day grace period after your PayGlue subscription ended is over, "
            "and your workspaces are now paused. Paused means: purchases at your "
            "payment provider no longer unlock anything in Ghost, and the "
            "dashboard shows only the plans page and your account settings.\n\n"
            "Nothing was deleted. Your connections, mappings, paywalls and buttons "
            "are all still there. Pick a plan in your dashboard and everything "
            "picks up where it left off.\n\n"
            "If you are done with PayGlue, you can delete your account yourself "
            "from the account settings, and we will remove your data.\n\n" + _SIGN_OFF
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
        ("tenants", "0052_pg298_lapse_fields"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]

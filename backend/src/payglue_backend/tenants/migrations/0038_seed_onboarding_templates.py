# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Seed the two onboarding emails.

Built here rather than in Brevo for one concrete reason: the day-15 mail must
only go to someone who has not cancelled, and that state already lives in this
backend. send_lifecycle_emails polls Creem daily and knows it. Brevo would have
needed PayGlue to push a cancellation webhook it does not otherwise send.

André's copy, unchanged apart from the placeholders. They go out through the
same branded template as every other PayGlue email.
"""
from django.db import migrations

_SIGN_OFF = "__\nCheers,\nAndré"

WELCOME_SUBJECT = "Welcome to PayGlue"
WELCOME_BODY = (
    "Hey,\n\n"
    "my name is André, I'm the founder of PayGlue.\n\n"
    "I built this because Ghost only really works with Stripe out of the box, "
    "and a lot of creators (myself included) needed something that works with "
    "whatever payment provider they actually use.\n\n"
    "Here are 3 things to get started:\n\n"
    "1. Connect your Ghost blog: https://app.payglue.io then Connection, then Ghost CMS\n"
    "2. Connect a payment provider: same Connection menu, pick whichever one you use "
    "(Polar, Lemon Squeezy, PayPal, Gumroad, Paddle, Ko-fi, Patreon or Creem)\n"
    "3. Check the docs if anything's unclear: https://docs.payglue.io\n\n"
    "P.S. Why did you sign up? What are you building? Hit reply and let me know, "
    "I read and answer every email myself.\n\n" + _SIGN_OFF
)

DAY15_SUBJECT = "How's it going with PayGlue?"
DAY15_BODY = (
    "Hey,\n\n"
    "quick check-in, it's been about two weeks since you started with PayGlue. "
    "How's it going so far?\n\n"
    "Did Ghost, your payment provider, and your first product mapping all connect "
    "smoothly, or did you get stuck somewhere along the way?\n\n"
    "If anything was confusing, missing, or just annoying, hit reply and tell me. "
    "I read every email myself, and it's genuinely how PayGlue gets better.\n\n"
    + _SIGN_OFF
)

TEMPLATES = [
    {"trigger": "onboarding_welcome", "subject": WELCOME_SUBJECT, "body": WELCOME_BODY},
    {"trigger": "onboarding_day15", "subject": DAY15_SUBJECT, "body": DAY15_BODY},
]


def seed(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    for row in TEMPLATES:
        Template.objects.get_or_create(
            trigger=row["trigger"],
            defaults={"subject": row["subject"], "body": row["body"], "enabled": True},
        )


def unseed(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    Template.objects.filter(trigger__in=[r["trigger"] for r in TEMPLATES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0037_alter_lifecycleemaillog_trigger_and_more"),
    ]

    operations = [migrations.RunPython(seed, unseed)]

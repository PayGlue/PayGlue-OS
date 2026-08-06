# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Seed the two onboarding emails.

Built here rather than in an external mail tool for one concrete reason: the
day-15 mail must only go to someone who has not cancelled, and that state
already lives in this backend. send_lifecycle_emails polls the billing provider
daily and knows it. An external tool would have needed a cancellation webhook
this backend does not otherwise send.

The seeded copy is deliberately plain and carries no links, no sender name and
no addresses. Every installation runs on its own domain, so anything specific
belongs in the template rows, not in this file. Seeded disabled for the same
reason 0017 and 0019 are: nothing should reach a real customer until whoever
runs the installation has read the wording and turned it on.
"""
from django.db import migrations

# Repeated rather than imported: a migration has to keep saying what it said the
# day it ran, so it must not follow a constant that runtime code may reword.
_SIGN_OFF = "__\nCheers,\nPayGlue - Team"

WELCOME_SUBJECT = "Welcome to PayGlue"
WELCOME_BODY = (
    "Hey,\n\n"
    "welcome to PayGlue. It connects your Ghost site to whichever payment "
    "provider you actually use, so a purchase there turns into access here.\n\n"
    "Three things to get started:\n\n"
    "1. Connect your Ghost site: open Connections, then Ghost CMS\n"
    "2. Connect a payment provider: same menu, pick the one you use "
    "(Polar, Lemon Squeezy, PayPal, Gumroad, Paddle, Ko-fi, Patreon or Creem)\n"
    "3. Map your first product, so a purchase grants the right Ghost access\n\n"
    "If anything is unclear, just reply to this email.\n\n" + _SIGN_OFF
)

DAY15_SUBJECT = "How is it going with PayGlue?"
DAY15_BODY = (
    "Hey,\n\n"
    "it has been about two weeks since you started with PayGlue. How is it "
    "going so far?\n\n"
    "Did Ghost, your payment provider and your first product mapping all "
    "connect smoothly, or did you get stuck somewhere along the way?\n\n"
    "If anything was confusing or missing, reply to this email and say so.\n\n"
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
            defaults={"subject": row["subject"], "body": row["body"], "enabled": False},
        )


def unseed(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    Template.objects.filter(trigger__in=[r["trigger"] for r in TEMPLATES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0037_alter_lifecycleemaillog_trigger_and_more"),
    ]

    operations = [migrations.RunPython(seed, unseed)]

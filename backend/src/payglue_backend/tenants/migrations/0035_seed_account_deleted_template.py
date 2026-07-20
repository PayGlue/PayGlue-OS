# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Seed the account-deletion confirmation email.

There was a `subscription_ended` template but nothing for the account itself,
so the one action a user cannot undo was the one that produced no receipt.

The copy is deliberately in the past tense. Deletion is synchronous -- the rows
are gone before this sends -- so "will be deleted within 24 hours" would both
understate what happened and invent a deadline none of our documents carry. The
DPA's 30 days (Section 9) is an outer bound on the same promise, not a queue
this waits in.

The invoice caveat is not optional wording: the privacy policy commits to
retaining payment records for the statutory period, and GDPR Article 17(3)(b)
covers exactly that. A confirmation claiming everything is gone would be
contradicted by our own policy.
"""
from django.db import migrations

_SIGN_OFF = "__\nCheers,\nPayGlue - Team"

TRIGGER = "account_deleted"
SUBJECT = "Your PayGlue account has been deleted"
BODY = (
    "Hi,\n\n"
    "Your PayGlue account has been deleted. This is your confirmation.\n\n"
    "It has already happened, not scheduled: your profile, the publications you "
    "solely owned, their connections, paywalls, buy buttons, pricing tables, "
    "product mappings, stored provider credentials and webhook history were "
    "removed when you confirmed, along with your sign-in account.\n\n"
    "Two things are worth knowing:\n\n"
    "Your Ghost site is untouched. Member access lives in your own Ghost "
    "instance, not in PayGlue, so nobody loses access because you closed this "
    "account.\n\n"
    "Invoices and payment records are the one exception. Tax law requires us to "
    "keep them for a statutory period, so they are not deleted on request. GDPR "
    "Article 17(3)(b) provides for exactly this case. They are held by our "
    "payment provider for billing, not used for anything else.\n\n"
    "If you did not do this, reply immediately.\n\n" + _SIGN_OFF
)


def seed(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    Template.objects.get_or_create(
        trigger=TRIGGER,
        defaults={"subject": SUBJECT, "body": BODY, "enabled": True},
    )


def unseed(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    Template.objects.filter(trigger=TRIGGER).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0034_alter_lifecycleemaillog_trigger_and_more"),
    ]

    operations = [migrations.RunPython(seed, unseed)]

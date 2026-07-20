# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Correct two things in the account-deletion confirmation.

The invoice paragraph implied PayGlue holds payment records and is legally
required to keep them. It does not hold them at all: they sit with the payment
provider, who is merchant of record for the purchase. Saying "we keep them"
claims custody of data we have no access to, and offers to delete something we
could not delete if we wanted to.

Backups were not mentioned. From 2026-08-01 there is a 7-day rolling backup
window, so a copy of a deleted account can survive there for up to a week.
Stating it before the backups exist over-discloses for a few days, which is the
harmless direction; discovering it afterwards and having to correct a "your
data is gone" email is not.

Rewrites only rows still holding the exact 0035 copy, the same guard 0028 used:
anything edited in the admin is André's and stays his.
"""
from django.db import migrations

_SIGN_OFF = "__\nCheers,\nPayGlue - Team"

TRIGGER = "account_deleted"

_PREAMBLE = (
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
)

OLD_BODY = (
    _PREAMBLE
    + "Invoices and payment records are the one exception. Tax law requires us to "
    "keep them for a statutory period, so they are not deleted on request. GDPR "
    "Article 17(3)(b) provides for exactly this case. They are held by our "
    "payment provider for billing, not used for anything else.\n\n"
    "If you did not do this, reply immediately.\n\n" + _SIGN_OFF
)

NEW_BODY = (
    _PREAMBLE.replace("Two things are worth knowing:", "A few things are worth knowing:")
    + "Invoices and payment records are not ours to delete. They sit with our "
    "payment provider, who is the merchant of record for your purchase and is "
    "required to keep them for the statutory period. GDPR Article 17(3)(b) "
    "covers exactly this. We hold no copy and cannot remove theirs.\n\n"
    "Encrypted backups are kept on a 7-day rolling window, so a copy of your "
    "data can survive there for up to seven days before it ages out. Nothing "
    "reads from those backups except disaster recovery.\n\n"
    "If you did not do this, reply immediately.\n\n" + _SIGN_OFF
)


def update(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    template = Template.objects.filter(trigger=TRIGGER).first()
    if template is None:
        Template.objects.create(trigger=TRIGGER, subject="Your PayGlue account has been deleted", body=NEW_BODY, enabled=True)
        return
    if template.body == OLD_BODY:
        template.body = NEW_BODY
        template.save(update_fields=["body"])


def revert(apps, schema_editor):
    Template = apps.get_model("tenants", "LifecycleEmailTemplate")
    template = Template.objects.filter(trigger=TRIGGER).first()
    if template is not None and template.body == NEW_BODY:
        template.body = OLD_BODY
        template.save(update_fields=["body"])


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0035_seed_account_deleted_template"),
    ]

    operations = [migrations.RunPython(update, revert)]

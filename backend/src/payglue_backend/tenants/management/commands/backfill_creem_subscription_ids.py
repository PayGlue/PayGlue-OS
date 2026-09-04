# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-298: one-off repair for accounts created before the signup stored the
Creem subscription id.

For every non-tester BillingAccount without a stored id, looks the
subscription up by the owner's email (the same lookup the daily poll uses
now) and stores the id, the customer id and the status Creem reports.

--assume-active records "active" as the last known status instead of the
real one. That makes the next poll treat a subscription that is already
past_due or ended as a transition and start the matching phase. Use it for
accounts that are known paying customers; without it an old, dead
subscription is recorded as dead and nothing starts.

    python manage.py backfill_creem_subscription_ids --dry-run
    python manage.py backfill_creem_subscription_ids --assume-active
"""
from django.core.management.base import BaseCommand

from payglue_backend.tenants import lapse
from payglue_backend.tenants.models import BillingAccount


class Command(BaseCommand):
    help = "Store the Creem subscription id for accounts that never got one at signup."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report only, write nothing.")
        parser.add_argument(
            "--assume-active",
            action="store_true",
            help="Record last known status as active so the next poll starts a phase for dead subscriptions.",
        )
        parser.add_argument("--email", action="append", default=[], help="Restrict to these owner emails.")

    def handle(self, *args, **options):
        accounts = BillingAccount.objects.filter(is_tester=False, creem_subscription_id="").select_related(
            "owner", "plan"
        )
        if options["email"]:
            accounts = accounts.filter(owner__email__in=options["email"])

        if not accounts:
            self.stdout.write("Nothing to do: every account has a subscription id.")
            return

        for account in accounts:
            found = lapse.latest_creem_subscription_for_account(account)
            if found is None:
                self.stdout.write(f"{account.owner.email} ({account.plan.key}): no Creem subscription found")
                continue
            sub, _key, _base, sandbox = found
            sub_id, customer_id = lapse.subscription_ids(sub)
            status = str(sub.get("status") or "")
            recorded = "active" if options["assume_active"] else status
            self.stdout.write(
                f"{account.owner.email} ({account.plan.key}): {sub_id} status={status}"
                f"{' sandbox' if sandbox else ''} -> last_known={recorded}"
            )
            if options["dry_run"]:
                continue
            account.creem_subscription_id = sub_id
            if customer_id:
                account.creem_customer_id = customer_id
            account.last_known_subscription_status = recorded
            account.save(
                update_fields=[
                    "creem_subscription_id",
                    "creem_customer_id",
                    "last_known_subscription_status",
                    "updated_at",
                ]
            )

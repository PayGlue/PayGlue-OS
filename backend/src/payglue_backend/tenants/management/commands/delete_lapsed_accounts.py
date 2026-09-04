# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Kept as a name only. PG-190 built this to delete accounts 30 days after
a confirmed cancellation; PG-298 replaced the ending with a pause, see
pause_lapsed_accounts. The scheduler still calls this name, so it forwards
there rather than silently doing nothing or, worse, still deleting.

Self-service deletion lives in the dashboard's danger zone; an operator can
delete from the Django admin. Neither is automatic any more.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Deprecated alias for pause_lapsed_accounts. Accounts are paused after the grace period, not deleted."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        self.stdout.write("delete_lapsed_accounts is an alias for pause_lapsed_accounts since PG-298.")
        call_command("pause_lapsed_accounts", dry_run=options["dry_run"], stdout=self.stdout)

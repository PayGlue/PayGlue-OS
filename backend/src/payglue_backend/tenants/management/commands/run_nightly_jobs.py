# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The nightly chain as one command.

Until now the scheduler's start command chained seven management commands
with &&. Found live on 2026-09-04: every night only the first one produced
output, for weeks. The other six, among them the lifecycle poll that
watches paying customers and the purge that scrubs raw webhook payloads,
never ran. 118 payloads older than the retention window were still there,
and a support status was days stale.

One process, one loop, no shell involved. Each job runs on its own; a job
that fails is logged with its traceback and the next one still runs. A
purge that trips must not be the reason a customer never hears that their
card failed. The exit code is non-zero if any job failed, so the scheduler
still shows the run as red.

    python manage.py run_nightly_jobs
    python manage.py run_nightly_jobs --dry-run   (passed on to jobs that take it)
"""
import traceback

from django.core.management import call_command, get_commands
from django.core.management.base import BaseCommand

# Order matters where one job feeds the next: the lifecycle poll sets the
# marks that pause_lapsed_accounts and expire_tester_access act on.
JOBS: list[tuple[str, bool]] = [
    ("enforce_downgrade_grace_periods", True),
    ("expire_tester_access", True),
    ("send_lifecycle_emails", True),
    ("pause_lapsed_accounts", True),
    ("purge_expired_logs", False),
    ("send_delivery_alerts", False),
    ("sync_support_statuses", False),
]


class Command(BaseCommand):
    help = "Run every nightly maintenance job in order, each isolated from the others."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Passed to the jobs that support it.")

    def handle(self, *args, **options):
        failed: list[str] = []
        installed = get_commands()
        for name, takes_dry_run in JOBS:
            if name not in installed:
                # A self-hosted installation ships without some of these
                # (the support status sync talks to our own tracker). Not
                # having a job is not a failure of the night.
                self.stdout.write(f"== {name}: not installed, skipped")
                continue
            self.stdout.write(f"== {name}")
            kwargs = {"dry_run": True} if (options["dry_run"] and takes_dry_run) else {}
            try:
                call_command(name, stdout=self.stdout, stderr=self.stderr, **kwargs)
            except Exception:  # noqa: BLE001, the point is to keep going
                failed.append(name)
                self.stderr.write(f"{name} failed:\n{traceback.format_exc()}")
        if failed:
            raise SystemExit(f"nightly jobs failed: {', '.join(failed)}")
        self.stdout.write("nightly jobs done")

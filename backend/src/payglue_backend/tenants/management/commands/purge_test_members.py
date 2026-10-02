# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-325: delete test members from Ghost after a publication's retention.

A sandbox or test-mode purchase creates a Ghost member with the
payglue-test label and no newsletter. On a demo site that is most members.
A publication can set, on its Ghost connection, how many days such members
stay; this job deletes the older ones. Off (0) means keep them, which is the
default, so nothing is deleted anywhere until somebody asks for it.

Only the label decides. It is written from the provider's own sandbox or
test flag, never from the address, so a real member cannot carry it.
"""
import logging

from django.core.management.base import BaseCommand

from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks import wiring
from payglue_backend.webhooks.models import IntegrationConfig

logger = logging.getLogger(__name__)

RETENTION_KEY = "test_member_retention_days"


def retention_days(metadata: object) -> int:
    if not isinstance(metadata, dict):
        return 0
    try:
        return max(int(metadata.get(RETENTION_KEY) or 0), 0)
    except (TypeError, ValueError):
        return 0


class Command(BaseCommand):
    help = "PG-325: delete Ghost members with the payglue-test label once they are older than the publication's retention."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="List what would be purged without deleting.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        configs = IntegrationConfig.objects.filter(provider_key="cms", enabled=True)
        publications = deleted = 0
        for config in configs:
            days = retention_days(config.metadata)
            if days <= 0:
                continue
            publications += 1
            if dry_run:
                self.stdout.write(f"{config.tenant_slug}: would purge test members older than {days} days")
                continue
            try:
                adapter = wiring.get_cms_adapter(config.provider_type or "ghost")
                result = adapter.purge_test_members(TenantContext(tenant_slug=config.tenant_slug), days)
                deleted += result.get("deleted", 0)
                self.stdout.write(
                    f"{config.tenant_slug}: deleted {result.get('deleted', 0)} test members older than {days} days"
                    + (f", {result['failed']} failed" if result.get("failed") else "")
                )
            except Exception:
                logger.exception("purge_test_members: failed for tenant %s", config.tenant_slug)
        self.stdout.write(
            f"Done. publications={publications} deleted={deleted}{' (dry-run)' if dry_run else ''}"
        )

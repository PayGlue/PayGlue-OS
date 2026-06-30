# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.db import migrations


class Migration(migrations.Migration):
    """
    Original CreateModel migration replaced with no-op.
    Actual table creation moved to 0010_create_paywallconfig_final
    to handle cases where this migration was incorrectly recorded as applied.
    """

    dependencies = [
        ('webhooks', '0007_add_skipped_status_to_webhookinboundevent'),
    ]

    operations = []

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Rename the two support columns off the tracker they used to point at.

Written by hand rather than generated, because the generator asks whether a
disappearing column and an appearing one are the same field and gets it wrong
in a non-interactive shell. Answered here once, in the file: they are the same
field, so this renames and keeps every row.
"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0046_changelogentry"),
    ]

    operations = [
        migrations.RenameField(
            model_name="supportrequest",
            old_name="linear_issue_id",
            new_name="tracker_issue_id",
        ),
        migrations.RenameField(
            model_name="supportrequest",
            old_name="linear_identifier",
            new_name="tracker_identifier",
        ),
    ]

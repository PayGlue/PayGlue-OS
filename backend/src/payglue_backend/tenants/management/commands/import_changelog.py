# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Load changelog entries from JSON (PG-228).

Written for the one-off move of the existing entries out of the static site's
data file and into the database, and kept afterwards because a changelog is
exactly the kind of thing somebody eventually wants to restore from a backup or
seed on a fresh installation.

Deliberately a command that reads a file rather than a data migration. This
repository is mirrored to the public PayGlue-OS repo, and a data migration would
carry our own announcements into it, where they mean nothing to anybody running
their own copy. The command is content-free; the content stays outside.

    python manage.py import_changelog entries.json
    cat entries.json | python manage.py import_changelog -

The JSON is a list of objects using the same keys the model does. `title` is
required, everything else falls back to the model default. Entries are matched
on title so a second run updates rather than duplicates.
"""

import json
import sys
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from payglue_backend.tenants.models import ChangelogEntry

FIELDS = (
    "date",
    "version",
    "category",
    "status",
    "badge",
    "meta",
    "description",
    "items",
    "show_in_bell",
    "bell_body",
)


class Command(BaseCommand):
    help = "Load changelog entries from a JSON file, or from stdin with '-'."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("path", help="Path to a JSON file, or '-' for stdin")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen and write nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        raw = sys.stdin.read() if options["path"] == "-" else open(options["path"]).read()

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CommandError(f"Not valid JSON: {exc}") from exc

        if not isinstance(payload, list):
            raise CommandError("Expected a list of entries at the top level.")

        created = updated = 0
        for index, item in enumerate(payload):
            if not isinstance(item, dict) or not item.get("title"):
                raise CommandError(f"Entry {index} has no title.")

            values = {field: item[field] for field in FIELDS if field in item}

            # Accepted as a string because that is what a JSON export carries.
            # Left alone when absent, so the model default (now) applies and a
            # partial import does not silently backdate anything.
            if item.get("published_at"):
                parsed = parse_datetime(item["published_at"])
                if parsed is None:
                    raise CommandError(
                        f"Entry {index}: published_at is not a datetime: {item['published_at']!r}"
                    )
                values["published_at"] = parsed

            if options["dry_run"]:
                exists = ChangelogEntry.objects.filter(title=item["title"]).exists()
                created, updated = (created, updated + 1) if exists else (created + 1, updated)
                continue

            # Matched on title rather than on a generated id: the source of this
            # data is a hand-written file with no ids, and running the import
            # twice should correct entries rather than double them.
            _, was_created = ChangelogEntry.objects.update_or_create(
                title=item["title"], defaults=values
            )
            created, updated = (created + 1, updated) if was_created else (created, updated + 1)

        prefix = "Would create" if options["dry_run"] else "Created"
        verb = "update" if options["dry_run"] else "updated"
        self.stdout.write(f"{prefix} {created}, {verb} {updated}.")

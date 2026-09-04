# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from payglue_backend.tenants.models import ChangelogEntry

pytestmark = pytest.mark.django_db


def _load(tmp_path, payload) -> str:
    path = tmp_path / "entries.json"
    path.write_text(json.dumps(payload))
    out = StringIO()
    call_command("import_changelog", str(path), stdout=out)
    return out.getvalue()


def test_loads_entries_with_every_field(tmp_path) -> None:
    _load(
        tmp_path,
        [
            {
                "title": "Something shipped",
                "date": "August 2026",
                "version": "v0.31",
                "category": "Website",
                "status": "done",
                "badge": "Shipped",
                "description": "The long version.",
                "items": ["One", "Two"],
                "show_in_bell": True,
                "bell_body": "The short version.",
                "published_at": "2026-08-10T12:00:00Z",
            }
        ],
    )

    entry = ChangelogEntry.objects.get()
    assert entry.version == "v0.31"
    assert entry.items == ["One", "Two"]
    assert entry.show_in_bell is True
    assert entry.bell_body == "The short version."
    assert entry.published_at.isoformat().startswith("2026-08-10T12:00:00")


def test_running_twice_corrects_rather_than_doubles(tmp_path) -> None:
    """The source is a hand-written file with no ids. Matching on title means a
    second run fixes a typo instead of leaving two versions of the entry."""
    _load(tmp_path, [{"title": "Same title", "description": "First wording."}])
    _load(tmp_path, [{"title": "Same title", "description": "Corrected wording."}])

    assert ChangelogEntry.objects.count() == 1
    assert ChangelogEntry.objects.get().description == "Corrected wording."


def test_dry_run_writes_nothing(tmp_path) -> None:
    path = tmp_path / "entries.json"
    path.write_text(json.dumps([{"title": "Not saved", "description": "x"}]))
    out = StringIO()

    call_command("import_changelog", str(path), "--dry-run", stdout=out)

    assert ChangelogEntry.objects.count() == 0
    assert "Would create 1" in out.getvalue()


def test_an_entry_without_a_title_stops_the_import(tmp_path) -> None:
    """Titles are how a second run finds an existing entry. Without one the
    import would create a duplicate on every run, silently."""
    path = tmp_path / "entries.json"
    path.write_text(json.dumps([{"description": "No title here."}]))

    with pytest.raises(CommandError, match="no title"):
        call_command("import_changelog", str(path))


def test_a_broken_published_at_stops_the_import_instead_of_guessing(tmp_path) -> None:
    path = tmp_path / "entries.json"
    path.write_text(json.dumps([{"title": "T", "published_at": "last Tuesday"}]))

    with pytest.raises(CommandError, match="not a datetime"):
        call_command("import_changelog", str(path))


def test_reads_from_stdin(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.stdin", StringIO(json.dumps([{"title": "Piped in", "description": "x"}]))
    )

    call_command("import_changelog", "-", stdout=StringIO())

    assert ChangelogEntry.objects.get().title == "Piped in"

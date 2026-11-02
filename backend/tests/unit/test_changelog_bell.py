# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The dashboard bell reads the helpdesk's changelog: only entries with the bell
label, newest first, capped, with a short plain-text teaser and a link to the
full entry. Without a helpdesk it falls back to our own table."""
from datetime import datetime, timezone
from unittest import mock

from django.test import override_settings

from payglue_backend.http import changelog
from payglue_backend.tenants import helpdesk

ROWS = [
    {
        "id": "changelog_3",
        "title": "Support inside the dashboard",
        "content": "## Heading\n\nAsk us **anything** from the [dashboard](https://x).\n\nMore detail.",
        "publishedAt": "2026-10-27T10:00:00Z",
        "categories": [{"name": "Shipped"}, {"name": "App"}],
    },
    {
        "id": "changelog_2",
        "title": "Website tweak",
        "content": "Footer.",
        "publishedAt": "2026-10-26T10:00:00Z",
        "categories": [{"name": "Website"}],
    },
]


NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def _bell(rows, now=NOW):
    with mock.patch.object(changelog, "cache") as fake_cache, mock.patch.object(
        helpdesk, "published_changelog", return_value=rows
    ), mock.patch.object(changelog.timezone, "now", return_value=now), override_settings(
        FEEDBACKOS_URL="https://hub.example.com", FEEDBACKOS_API_KEY="k"
    ):
        fake_cache.get.return_value = None
        return changelog._helpdesk_bell()


def test_only_entries_with_the_bell_label_reach_the_bell() -> None:
    entries = _bell(ROWS)
    assert [e["anchor"] for e in entries] == ["changelog_3"]
    assert entries[0]["url"] == "https://hub.example.com/changelog/changelog_3"


def test_entries_older_than_thirty_days_leave_the_bell() -> None:
    old = {**ROWS[0], "id": "changelog_1", "publishedAt": "2026-09-14T10:00:00Z"}
    assert [e["anchor"] for e in _bell([ROWS[0], old])] == ["changelog_3"]
    assert _bell([ROWS[0]], now=datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)) == []


def test_the_teaser_is_the_first_text_paragraph_without_markdown() -> None:
    assert _bell(ROWS)[0]["body"] == "Ask us anything from the dashboard."
    assert changelog._teaser("Ask us **anything** from the [dashboard](https://x).") == (
        "Ask us anything from the dashboard."
    )
    long = changelog._teaser("word " * 80)
    assert long.endswith("…") and len(long) <= 201


def test_the_teaser_decodes_entities_the_helpdesk_stores() -> None:
    assert changelog._teaser("Open Settings &gt; Support &amp; ask.") == "Open Settings > Support & ask."


def test_no_helpdesk_means_fall_back() -> None:
    assert _bell(None) is None


PAGE_ROWS = [
    {
        "id": "changelog_9",
        "title": "Support inside the dashboard",
        "content": "First paragraph with a [link](https://x).\n\nSecond one &gt; here.\n\n- One\n- Two",
        "publishedAt": "2026-10-27T10:00:00Z",
        "categories": [{"name": "Shipped"}, {"name": "App"}],
    },
    {
        "id": "changelog_8",
        "title": "Why we will not build X",
        "content": "Reasoning.",
        "publishedAt": "2026-09-02T10:00:00Z",
        "categories": [{"name": "Won't build"}, {"name": "Backend"}],
    },
]


def _page(rows, legacy=()):
    with mock.patch.object(changelog, "cache") as fake_cache, mock.patch.object(
        helpdesk, "all_published_changelog", return_value=rows
    ), mock.patch.object(changelog.ChangelogEntry, "objects") as objects:
        fake_cache.get.return_value = None
        objects.all.return_value = list(legacy)
        return changelog._helpdesk_page()


def test_page_entries_take_status_area_and_body_from_the_helpdesk() -> None:
    first, second = _page(PAGE_ROWS)
    assert first["anchor"] == "support-inside-the-dashboard"
    assert first["date"] == "October 2026"
    assert (first["status"], first["badge"], first["category"]) == ("done", "Shipped", "Dashboard")
    assert first["description"] == "First paragraph with a [link](https://x).\n\nSecond one > here."
    assert first["items"] == ["One", "Two"]
    assert (second["status"], second["badge"], second["category"]) == (
        "wont-build",
        "Won't build",
        "Backend",
    )
    assert "items" not in second


def test_old_entries_keep_their_version_and_category() -> None:
    old = mock.Mock(title="Why we will not build X", version="v0.4", category="Providers", meta="")
    entries = _page(PAGE_ROWS, legacy=[old])
    assert entries[1]["version"] == "v0.4"
    assert entries[1]["category"] == "Providers"


def test_no_helpdesk_page_means_fall_back() -> None:
    assert _page(None) is None

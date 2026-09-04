# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The changelog, read by two very different callers (PG-228).

The public marketing page fetches this while it is being built, so it has to
answer without a session: at build time there is no user, only a machine
assembling HTML. The dashboard bell fetches it in the browser and wants a short,
filtered slice of the same rows.

Deliberately unauthenticated. Everything here is published copy that already
appears on a page anybody can read, and requiring a token would mean handing the
static build a credential to say something it will print in plain text anyway.
Nothing user-specific is in the response, and nothing here is writable.
"""

import json

from django.http import HttpRequest, HttpResponse
from django.utils.text import slugify
from django.views import View

from payglue_backend.tenants.models import ChangelogEntry

# What the bell shows. The popup is a 16rem column in the sidebar, and the old
# hardcoded version rendered its whole array, so it grew until the oldest entry
# had to be deleted by hand to keep it readable. Enforced here rather than left
# to whoever writes the next entry.
BELL_LIMIT = 4


def _anchor(entry: ChangelogEntry) -> str:
    """The id the entry gets on the public page, and the target the bell links
    to. Derived from the title here rather than on either side, so the page and
    the bell cannot drift apart: an entry the bell links to always exists on the
    page under exactly that name. Titles are unique, the import matches on them.

    Renaming an entry moves its anchor and breaks a link somebody saved. That is
    accepted: a stored slug would have to be kept in step with the title by hand,
    and this whole change exists to stop maintaining the same thing twice.
    """
    return slugify(entry.title)


def _page_entry(entry: ChangelogEntry) -> dict[str, object]:
    """The shape the public page renders. Mirrors what the static data file
    carried before this became a table, so the page's markup did not change."""
    payload: dict[str, object] = {
        "anchor": _anchor(entry),
        "date": entry.date,
        "status": entry.status,
        "title": entry.title,
        "description": entry.description,
        "publishedAt": entry.published_at.isoformat(),
    }
    # Absent rather than empty: the page treats these as optional and renders
    # nothing for them, and an empty string would draw an empty badge.
    if entry.version:
        payload["version"] = entry.version
    if entry.category:
        payload["category"] = entry.category
    if entry.badge:
        payload["badge"] = entry.badge
    if entry.meta:
        payload["meta"] = entry.meta
    if entry.items:
        payload["items"] = entry.items
    return payload


def _bell_entry(entry: ChangelogEntry) -> dict[str, object]:
    """Title, two lines, and a way to read the rest.

    The body falls back to the page description when no bell copy was written,
    which reads cramped but beats an empty row. The anchor is what makes the
    short version acceptable: the bell is a teaser, and it has to be able to
    hand somebody the full entry rather than dropping them at the top of a page
    with forty-five of them.
    """
    return {
        "anchor": _anchor(entry),
        "title": entry.title,
        "body": entry.bell_body or entry.description,
        "publishedAt": entry.published_at.isoformat(),
    }


class ChangelogView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        wants_bell = request.GET.get("bell") == "1"

        entries = ChangelogEntry.objects.all()
        if wants_bell:
            entries = entries.filter(show_in_bell=True)[:BELL_LIMIT]
            payload = [_bell_entry(entry) for entry in entries]
        else:
            payload = [_page_entry(entry) for entry in entries]

        return HttpResponse(
            json.dumps({"entries": payload}),
            content_type="application/json",
        )

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

import html
import json
import re
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.text import slugify
from django.views import View

from payglue_backend.tenants import helpdesk
from payglue_backend.tenants.models import ChangelogEntry

# What the bell shows. The popup is a 16rem column in the sidebar, and the old
# hardcoded version rendered its whole array, so it grew until the oldest entry
# had to be deleted by hand to keep it readable. Enforced here rather than left
# to whoever writes the next entry.
BELL_LIMIT = 4
# And for how long. Without a cut-off an old entry stays in the bell for as
# long as fewer than four newer ones follow it.
BELL_MAX_AGE = timedelta(days=30)


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


# The bell reads the helpdesk's changelog when one is configured (the changelog
# moved there), cached briefly so every dashboard load does not become a call.
_HELPDESK_BELL_CACHE_KEY = "changelog:helpdesk-bell"
_HELPDESK_BELL_TTL = 300
# Which entries reach the bell: the ones carrying this label. Customers hear
# about changes to the dashboard, not about every website or backend tweak.
_DEFAULT_BELL_LABEL = "App"
_TEASER_LIMIT = 200


def _teaser(markdown: str) -> str:
    """The first paragraph of an entry as plain text, cut at a word boundary."""
    for block in (markdown or "").split("\n\n"):
        if block.lstrip().startswith("#"):
            continue  # a heading says little on its own in two lines
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", block)
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"^\s*(#+|[-*]|\d+\.)\s+", "", text, flags=re.M)
        text = re.sub(r"[*_`>]", "", text)
        # The helpdesk stores some characters as entities ("Settings &gt; Support").
        text = " ".join(html.unescape(text).split())
        if text:
            if len(text) <= _TEASER_LIMIT:
                return text
            return text[: _TEASER_LIMIT].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return ""


def _is_recent(published_at: str, now: datetime) -> bool:
    """Whether an entry was published within the bell's age limit."""
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    return now - published <= BELL_MAX_AGE


def _helpdesk_bell() -> list[dict[str, object]] | None:
    """Bell entries from the helpdesk's changelog, or None to fall back."""
    cached = cache.get(_HELPDESK_BELL_CACHE_KEY)
    if cached is not None:
        return cached
    rows = helpdesk.published_changelog()
    if rows is None:
        return None
    label = (getattr(settings, "FEEDBACKOS_BELL_LABEL", "") or _DEFAULT_BELL_LABEL).strip().lower()
    now = timezone.now()
    picked = [
        row
        for row in rows
        if any((c.get("name") or "").strip().lower() == label for c in row.get("categories") or [])
        and _is_recent(row.get("publishedAt") or "", now)
    ][:BELL_LIMIT]
    entries = [
        {
            "anchor": row["id"],
            "title": html.unescape(row.get("title") or ""),
            "body": _teaser(row.get("content") or ""),
            "publishedAt": row.get("publishedAt") or "",
            "url": helpdesk.public_url(f"changelog/{row['id']}"),
        }
        for row in picked
        if row.get("id")
    ]
    cache.set(_HELPDESK_BELL_CACHE_KEY, entries, _HELPDESK_BELL_TTL)
    return entries


# The public page reads the helpdesk's changelog too, in the shape the page has
# always rendered. Labels carry what used to be separate fields: one says what
# kind of change it was, one which part of PayGlue it touched.
_HELPDESK_PAGE_CACHE_KEY = "changelog:helpdesk-page"
_HELPDESK_PAGE_TTL = 300
_LABEL_STATUS = {
    "shipped": ("done", "Shipped"),
    "fixed": ("done", "Fixed"),
    "in progress": ("in-progress", "In progress"),
    "pivot": ("pivot", "Pivot"),
    "reconsidered": ("reconsidered", "Reconsidered"),
    "won't build": ("wont-build", "Won't build"),
}
_LABEL_AREA = {"app": "Dashboard", "website": "Website", "backend": "Backend"}
_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _month(published_at: str) -> str:
    """"October 2026" from an ISO timestamp, in English whatever the server
    locale, because the page is English."""
    try:
        moment = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return ""
    return f"{_MONTHS[moment.month - 1]} {moment.year}"


def _split_content(markdown: str) -> tuple[str, list[str]]:
    """The entry body as the page's description plus bullet items. Paragraphs
    stay apart with a blank line; the page keeps line breaks."""
    paragraphs: list[str] = []
    items: list[str] = []
    for block in html.unescape(markdown or "").split("\n\n"):
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue
        if all(re.match(r"^[-*]\s+", line) for line in lines):
            items.extend(re.sub(r"^[-*]\s+", "", line) for line in lines)
        elif not lines[0].startswith("#"):
            paragraphs.append(" ".join(lines))
    return "\n\n".join(paragraphs), items


def _helpdesk_page() -> list[dict[str, object]] | None:
    """Page entries from the helpdesk's changelog, or None to fall back.

    Entries that came over from our own table keep the version and category
    they had there, matched by title: the helpdesk has no field for either, and
    losing the version on fifty old entries would rewrite history.
    """
    cached = cache.get(_HELPDESK_PAGE_CACHE_KEY)
    if cached is not None:
        return cached
    rows = helpdesk.all_published_changelog()
    if not rows:
        return None
    legacy = {entry.title: entry for entry in ChangelogEntry.objects.all()}
    entries: list[dict[str, object]] = []
    for row in sorted(rows, key=lambda r: r.get("publishedAt") or "", reverse=True):
        title = html.unescape(row.get("title") or "").strip()
        if not title or not row.get("publishedAt"):
            continue
        labels = [(c.get("name") or "").strip().lower() for c in row.get("categories") or []]
        status, badge = next(
            (_LABEL_STATUS[label] for label in labels if label in _LABEL_STATUS), ("done", "")
        )
        description, items = _split_content(row.get("content") or "")
        old = legacy.get(title)
        entry: dict[str, object] = {
            "anchor": slugify(title),
            "date": _month(row["publishedAt"]),
            "status": status,
            "title": title,
            "description": description,
            "publishedAt": row["publishedAt"],
        }
        category = (old.category if old else "") or next(
            (_LABEL_AREA[label] for label in labels if label in _LABEL_AREA), ""
        )
        # Absent rather than empty, as in _page_entry.
        for key, value in (
            ("version", old.version if old else ""),
            ("category", category),
            ("badge", badge),
            ("meta", old.meta if old else ""),
        ):
            if value:
                entry[key] = value
        if items:
            entry["items"] = items
        entries.append(entry)
    cache.set(_HELPDESK_PAGE_CACHE_KEY, entries, _HELPDESK_PAGE_TTL)
    return entries


class ChangelogView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        wants_bell = request.GET.get("bell") == "1"

        entries = ChangelogEntry.objects.all()
        from_helpdesk = _helpdesk_bell() if wants_bell else None
        if from_helpdesk is not None:
            payload = from_helpdesk
        elif wants_bell:
            entries = entries.filter(show_in_bell=True)[:BELL_LIMIT]
            payload = [_bell_entry(entry) for entry in entries]
        else:
            from_helpdesk_page = _helpdesk_page()
            payload = (
                from_helpdesk_page
                if from_helpdesk_page is not None
                else [_page_entry(entry) for entry in entries]
            )

        return HttpResponse(
            json.dumps({"entries": payload}),
            content_type="application/json",
        )

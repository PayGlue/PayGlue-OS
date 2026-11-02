# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Support requests as tickets in a FeedbackOS (Quackback) helpdesk (PG-360).

The successor to the issue tracker support used before. A request from the
dashboard form becomes a customer ticket there, under the ticket type that
matches its topic, with the customer as requester. From then on the helpdesk
owns the conversation: it confirms receipt, carries replies by email in both
directions and mails status changes, so this side sends none of that itself.

Three calls, all one-way from here: find or create the customer, open the
ticket (plus an internal note with what only the team may see), and read the
ticket's state back for the dashboard. Every call is best-effort. A request
that cannot reach the helpdesk is still stored and still mailed to us the old
way, because losing the request would be worse than losing the ticket.

Configured with FEEDBACKOS_URL and FEEDBACKOS_API_KEY (a team-role key). Either
empty means the helpdesk is off and every request is confirmed and forwarded by
email.
FEEDBACKOS_DEFAULT_ASSIGNEE optionally names the principal new tickets go to,
and FEEDBACKOS_DEFAULT_PRIORITY the priority they start with. Empty leaves
either unset.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10
# One status read per open request per run, capped so a runaway stays partial.
_MAX_STATUS_READS = 40

# Ticket ids the helpdesk hands out carry this prefix. It is how a stored
# request tells which system its ticket lives in, without a column for it.
TICKET_ID_PREFIX = "ticket_"

# Our form topics onto the helpdesk's ticket type slugs. A topic without a
# type there files under the helpdesk's default customer type.
TOPIC_TICKET_TYPES = {
    "integration": "integration-issue",
    "billing": "billing-or-plan",
    "bug": "something-is-broken",
    "feature": "feature-or-provider-request",
    "account": "account-or-team",
    "other": "something-else",
}

# The ticket's public stage onto our four statuses. Stages are the
# customer-facing projection the helpdesk keeps stable across renamed statuses.
_STAGE_TO_STATUS = {
    "received": "open",
    "in_progress": "in_progress",
    "awaiting_requester": "in_progress",
    "resolved": "done",
}

_type_ids_by_slug: dict[str, str] | None = None


def _base_url() -> str:
    # getattr with a default: an installation without these settings at all
    # simply has no helpdesk, the same as one that leaves them empty.
    return (getattr(settings, "FEEDBACKOS_URL", "") or "").strip().rstrip("/")


def _api_key() -> str:
    return (getattr(settings, "FEEDBACKOS_API_KEY", "") or "").strip()


def is_configured() -> bool:
    return bool(_base_url() and _api_key())


def owns(ticket_id: str) -> bool:
    """Whether a stored tracker id is a helpdesk ticket."""
    return bool(ticket_id) and ticket_id.startswith(TICKET_ID_PREFIX)


def _call(
    path: str, *, method: str = "GET", payload: dict | None = None, envelope: bool = False
) -> dict | list | None:
    """One request. Returns the response's `data` (or, with envelope, the whole
    body including `meta`), or None with a logged reason.

    The API key never appears in a log line or an exception message.
    """
    if not is_configured():
        return None
    url = f"{_base_url()}/api/v1/{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_api_key()}",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            body = response.read().decode()
            parsed = json.loads(body) if body else {}
            return parsed if envelope else parsed.get("data")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode()[:500]
        except Exception:  # noqa: BLE001 - diagnosis must not raise
            detail = "<body unreadable>"
        logger.warning("helpdesk: %s %s -> HTTP %s: %s", method, path, exc.code, detail)
    except (urllib.error.URLError, TimeoutError, ValueError, AttributeError) as exc:
        logger.warning("helpdesk: %s %s failed: %s", method, path, exc)
    return None


def _ticket_type_id(topic: str) -> str | None:
    """The helpdesk's ticket type for a form topic, by slug, or None."""
    global _type_ids_by_slug
    if _type_ids_by_slug is None:
        rows = _call("ticket-types")
        if not isinstance(rows, list):
            return None  # not cached, so a transient failure retries next time
        _type_ids_by_slug = {
            row["slug"]: row["id"]
            for row in rows
            if row.get("category") == "customer" and row.get("slug") and row.get("id")
        }
    slug = TOPIC_TICKET_TYPES.get(topic) or TOPIC_TICKET_TYPES["other"]
    found = _type_ids_by_slug.get(slug)
    if not found:
        logger.warning("helpdesk: no customer ticket type with slug %r", slug)
    return found


def _requester(email: str, name: str) -> str | None:
    """Find or create the customer by email. Returns their principal id."""
    payload: dict[str, str] = {"email": email}
    if name:
        payload["name"] = name[:200]
    data = _call("users/identify", method="POST", payload=payload)
    return data.get("principalId") if isinstance(data, dict) else None


def create_support_ticket(
    *, title: str, message: str, topic: str, email: str, name: str, internal_note: str
) -> tuple[str, str] | None:
    """Open a customer ticket. Returns (ticket id, reference), or None.

    The message goes into the ticket as the customer wrote it, because the
    customer sees the ticket. Anything only the team may read, such as the
    service PIN, goes into an internal note instead.
    """
    requester = _requester(email, name)
    if not requester:
        logger.warning("helpdesk: could not resolve the requester, ticket not opened")
        return None

    payload: dict[str, str] = {
        "title": title[:300],
        "description": message[:4000],
        "requesterPrincipalId": requester,
        # The message is the customer's own words; without this the helpdesk
        # shows it as if the API key had written it.
        "descriptionFromRequester": True,
    }
    priority = getattr(settings, "FEEDBACKOS_DEFAULT_PRIORITY", "")
    if priority:
        payload["priority"] = priority
    type_id = _ticket_type_id(topic)
    if type_id:
        payload["ticketTypeId"] = type_id
    else:
        payload["type"] = "customer"

    data = _call("tickets", method="POST", payload=payload)
    if not isinstance(data, dict) or not data.get("id"):
        logger.warning("helpdesk: ticket creation returned no id")
        return None

    ticket_id = data["id"]
    if internal_note:
        _call(
            f"tickets/{urllib.parse.quote(ticket_id)}/note",
            method="POST",
            payload={"content": _as_markdown_list(internal_note)[:4000]},
        )
    assignee = getattr(settings, "FEEDBACKOS_DEFAULT_ASSIGNEE", "")
    if assignee:
        _call(
            f"tickets/{urllib.parse.quote(ticket_id)}/assign",
            method="POST",
            payload={"assigneePrincipalId": assignee},
        )
    reference = str(data.get("reference") or (f"#{data['number']}" if data.get("number") else ""))
    return ticket_id, reference


def _as_markdown_list(text: str) -> str:
    """One line per fact. The helpdesk renders notes as markdown, where plain
    single newlines run together into one paragraph."""
    return "\n".join(f"- {line.strip()}" for line in text.splitlines() if line.strip())


def fetch_statuses(ticket_ids: list[str]) -> dict[str, str]:
    """Map helpdesk ticket id to one of our four statuses.

    Ids missing from the answer are absent from the result, so callers keep
    the status they stored.
    """
    ticket_ids = [t for t in ticket_ids if owns(t)][:_MAX_STATUS_READS]
    statuses: dict[str, str] = {}
    for ticket_id in ticket_ids:
        data = _call(f"tickets/{urllib.parse.quote(ticket_id)}")
        if not isinstance(data, dict):
            continue
        mapped = _STAGE_TO_STATUS.get(data.get("stage") or "")
        if not mapped and (data.get("status") or {}).get("category") == "closed":
            mapped = "done"
        if mapped:
            statuses[ticket_id] = mapped
    return statuses


def published_changelog(limit: int = 30) -> list[dict] | None:
    """The helpdesk's published changelog entries, newest first, each with its
    labels. None when the helpdesk is off or cannot be reached."""
    if not is_configured():
        return None
    rows = _call(f"changelog?published=true&limit={int(limit)}")
    return rows if isinstance(rows, list) else None


# The API hands out at most 100 entries per page. The page cap only guards
# against a cursor that never ends; the changelog is far below it.
_CHANGELOG_PAGE_SIZE = 100
_CHANGELOG_MAX_PAGES = 20


def all_published_changelog() -> list[dict] | None:
    """Every published changelog entry, following the API's pagination.

    None when the helpdesk is off or any page fails, so the caller falls back
    to what it had rather than publishing a list with a hole in it.
    """
    if not is_configured():
        return None
    rows: list[dict] = []
    cursor = ""
    for _ in range(_CHANGELOG_MAX_PAGES):
        path = f"changelog?published=true&limit={_CHANGELOG_PAGE_SIZE}"
        if cursor:
            path += f"&cursor={urllib.parse.quote(cursor)}"
        body = _call(path, envelope=True)
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            return None
        rows.extend(body["data"])
        pagination = (body.get("meta") or {}).get("pagination") or {}
        cursor = pagination.get("cursor") or ""
        if not pagination.get("hasMore") or not cursor:
            break
    return rows


def public_url(path: str = "") -> str:
    """An address on the helpdesk's public portal, or empty when it is off."""
    base = _base_url()
    return f"{base}/{path.lstrip('/')}" if base else ""


def _reset_cache() -> None:
    """Drop the memoised ticket types. For tests."""
    global _type_ids_by_slug
    _type_ids_by_slug = None

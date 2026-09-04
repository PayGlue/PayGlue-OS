# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Minimal issue tracker client for support requests, speaking Plane's REST API.

Two operations, both one-way from our side: open an issue, and read back the
state of issues we opened. That is the whole surface, and keeping it this small
is the point -- syncing comments in both directions is what makes a homegrown
helpdesk expensive, and the failure mode there is an internal comment reaching
a customer.

The module is named for the job rather than for the product behind it. This is
the second tracker the support flow has talked to, and the first move cost us
every call site. Now it costs this file.

Every call is best-effort. A support request that cannot reach the tracker is
still stored and still emailed to us, because losing the request would be far
worse than losing the ticket number.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_TIMEOUT = 10

# The tracker allows roughly 60 requests a minute and the status read costs one
# call per open request. Well above what a support queue produces, but a cap
# turns a runaway into a partial sync instead of a wall of 429s. Whatever is
# skipped is picked up by the next run.
_MAX_STATUS_READS = 40

# Every workflow state belongs to one of these groups. Mapping on the group
# rather than the state name means renaming a column in the tracker does not
# silently strand the dashboard on a status it cannot interpret. Our support
# project calls them Pending, Active, Closed and Cancelled, and none of those
# words appear here on purpose.
_STATE_GROUP_TO_STATUS = {
    "triage": "open",
    "backlog": "open",
    "unstarted": "open",
    "started": "in_progress",
    "completed": "done",
    "cancelled": "cancelled",
}

# Resolved once per process: the project's short key (the "ABC" in ABC-42) and
# the id -> group map for its states. Both change about never, and fetching
# them on every support request would triple the calls for no gain.
_project_key: str | None = None
_state_groups: dict[str, str] | None = None
_labels_by_name: dict[str, str] | None = None


def is_configured() -> bool:
    return bool(
        settings.PLANE_BASE_URL
        and settings.PLANE_API_KEY
        and settings.PLANE_WORKSPACE_SLUG
        and settings.PLANE_SUPPORT_PROJECT_ID
    )


def _project_url(path: str = "") -> str:
    # A base URL pasted with a trailing slash or an accidental /api is the most
    # common configuration mistake, and it produces a 404 on every call that
    # reads like a broken token.
    base = settings.PLANE_BASE_URL.strip().rstrip("/")
    if base.endswith("/api"):
        base = base[: -len("/api")]
    slug = urllib.parse.quote(settings.PLANE_WORKSPACE_SLUG.strip())
    project = urllib.parse.quote(settings.PLANE_SUPPORT_PROJECT_ID.strip())
    return f"{base}/api/v1/workspaces/{slug}/projects/{project}/{path}"


def _call(path: str, *, method: str = "GET", payload: dict | None = None) -> dict | None:
    """One request. Returns the parsed body, or None with a logged reason.

    The API key never appears in a log line or an exception message. Everything
    here is written on the assumption that these logs get pasted into an issue
    one day.
    """
    if not is_configured():
        logger.warning("tracker: not configured, skipping %s %s", method, path)
        return None

    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        _project_url(path),
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": settings.PLANE_API_KEY.strip(),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        # The status line alone says almost nothing. The body carries the actual
        # reason, and reading it is the difference between "403" and "this token
        # is not a member of that project".
        try:
            detail = exc.read().decode()[:500]
        except Exception:  # noqa: BLE001 - diagnosis must not raise
            detail = "<body unreadable>"
        logger.warning("tracker: %s %s -> HTTP %s: %s", method, path, exc.code, detail)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("tracker: %s %s failed: %s", method, path, exc)
    return None


def _load_project_key() -> str:
    """The short key issues are numbered with. Empty string if unavailable."""
    global _project_key
    if _project_key is None:
        data = _call("") or {}
        _project_key = data.get("identifier") or ""
    return _project_key


def _load_state_groups() -> dict[str, str]:
    """state id -> group, for the whole project."""
    global _state_groups
    if _state_groups is None:
        data = _call("states/")
        if data is None:
            return {}  # not cached, so a transient failure retries next time
        _state_groups = {
            s["id"]: s.get("group", "")
            for s in (data.get("results") or [])
            if s.get("id")
        }
    return _state_groups


def _load_labels() -> dict[str, str]:
    """lowercased label name -> id, for the whole project."""
    global _labels_by_name
    if _labels_by_name is None:
        data = _call("labels/")
        if data is None:
            return {}  # not cached, so a transient failure retries next time
        _labels_by_name = {
            l["name"].strip().lower(): l["id"]
            for l in (data.get("results") or [])
            if l.get("name") and l.get("id")
        }
    return _labels_by_name


def label_id_for(name: str) -> str | None:
    """Resolve a label by name, or None.

    Matching on the name rather than on a configured id means creating a label
    in the tracker is enough to make it work, with nothing to change in the
    environment. The trade is that renaming one silently stops the assignment,
    so a miss is logged rather than swallowed.
    """
    if not name:
        return None
    found = _load_labels().get(name.strip().lower())
    if not found:
        logger.warning("tracker: no label named %r in the support project", name)
    return found


def create_support_issue(
    *, title: str, description_html: str, label_names: list[str] | None = None
) -> tuple[str, str] | None:
    """Open an issue in the support project. Returns (id, identifier), or None.

    The identifier is what the customer is told to quote, so it is assembled
    from the project key and the number the tracker assigned. Without the key
    the issue still exists and the id is still stored; the customer just falls
    back to our own reference.
    """
    labels = []
    for name in label_names or []:
        found = label_id_for(name)
        if found:
            labels.append(found)
    # A fixed label on top of the topic one, which is how a staging deployment
    # marks its own tickets in a board it shares with production.
    if settings.PLANE_SUPPORT_LABEL_ID:
        labels.append(settings.PLANE_SUPPORT_LABEL_ID)

    payload = {
        "name": title[:255],
        "description_html": description_html,
        # A support ticket is "started" the moment it arrives, unlike a planned
        # work item where start_date is set later. Without it the ticket has no
        # anchor in the tracker's timeline/Gantt views.
        "start_date": timezone.localdate().isoformat(),
    }
    if labels:
        payload["labels"] = labels

    data = _call("issues/", method="POST", payload=payload)
    if not data or not data.get("id"):
        logger.warning("tracker: issue creation returned no id")
        return None

    key = _load_project_key()
    number = data.get("sequence_id")
    identifier = f"{key}-{number}" if key and number else ""
    return data["id"], identifier


def link_requester_email(issue_id: str, *, email: str, name: str = "") -> bool:
    """Tell the tracker which address this issue belongs to.

    Without this record the tracker shows no internal/external toggle on the
    comment box and refuses to send anything outward, so an answer typed there
    goes nowhere. It exists for issues that arrive by mail; ours arrive over
    the API, so we hand the address across ourselves (PG-266).

    Note the path: work-items, not issues. There is no alias under the older
    segment, and the wrong one answers 404 in a way that reads like a missing
    issue rather than a wrong URL.

    Best-effort like everything else here. A failure costs the toggle on one
    ticket, never the ticket, and never the request behind it. The endpoint is
    get-or-create, so a retry after a timeout is safe.
    """
    if not issue_id or not email:
        return False
    payload: dict[str, str] = {"requester_email": email}
    if name:
        payload["requester_name"] = name
    # issue, project and workspace are deliberately absent: the endpoint derives
    # all three from the URL, and sending them would only invite them to drift.
    path = f"work-items/{urllib.parse.quote(issue_id)}/email-link/"
    return _call(path, method="POST", payload=payload) is not None


def fetch_statuses(issue_ids: list[str]) -> dict[str, str]:
    """Map tracker issue id to one of our four statuses.

    Ids missing from the answer are simply absent from the result, so callers
    keep the last status they stored rather than inventing one. That covers a
    failed request and an issue somebody deleted in the tracker alike.
    """
    if not issue_ids:
        return {}

    groups = _load_state_groups()
    if not groups:
        return {}

    if len(issue_ids) > _MAX_STATUS_READS:
        logger.warning(
            "tracker: %s open requests, reading the first %s this run",
            len(issue_ids),
            _MAX_STATUS_READS,
        )
        issue_ids = issue_ids[:_MAX_STATUS_READS]

    statuses: dict[str, str] = {}
    for issue_id in issue_ids:
        # The REST API has no bulk lookup by id list, so this is one call per
        # open request. Cheap in practice: terminal requests are filtered out
        # by the caller and never come back.
        data = _call(f"issues/{urllib.parse.quote(issue_id)}/")
        if not data:
            continue
        mapped = _STATE_GROUP_TO_STATUS.get(groups.get(data.get("state", ""), ""))
        if mapped:
            statuses[issue_id] = mapped
    return statuses


def _reset_cache() -> None:
    """Drop the memoised project key and states. For tests."""
    global _project_key, _state_groups, _labels_by_name
    _project_key = None
    _state_groups = None
    _labels_by_name = None

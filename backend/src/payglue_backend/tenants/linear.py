# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Minimal Linear GraphQL client for support requests.

Two operations, both one-way from our side: open an issue, and read back the
state of issues we opened. That is the whole surface, and keeping it this small
is the point -- syncing comments in both directions is what makes a homegrown
helpdesk expensive, and the failure mode there is an internal comment reaching
a customer.

Every call is best-effort. A support request that cannot reach Linear is still
stored and still emailed to us, because losing the request would be far worse
than losing the ticket number.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

_API_URL = "https://api.linear.app/graphql"
_TIMEOUT = 10

# Linear groups every workflow state into one of these types. Mapping on type
# rather than state name means renaming a column in Linear does not silently
# strand the dashboard on a status it cannot interpret.
_STATE_TYPE_TO_STATUS = {
    "triage": "open",
    "backlog": "open",
    "unstarted": "open",
    "started": "in_progress",
    "completed": "done",
    "canceled": "cancelled",
}

_CREATE_ISSUE = """
mutation CreateSupportIssue($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue { id identifier }
  }
}
"""

_ISSUE_STATES = """
query SupportIssueStates($ids: [ID!]!) {
  issues(filter: { id: { in: $ids } }) {
    nodes { id state { type } }
  }
}
"""


def is_configured() -> bool:
    return bool(settings.LINEAR_API_KEY and settings.LINEAR_SUPPORT_TEAM_ID)


def _post(payload: bytes, auth: str) -> tuple[dict | None, str | None]:
    """One attempt. Returns (body, error) so the caller can decide about retrying."""
    request = urllib.request.Request(
        _API_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": auth},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return json.loads(response.read().decode()), None
    except urllib.error.HTTPError as exc:
        # The status line alone says almost nothing. Linear puts the actual
        # reason in the body, and reading it is the difference between "401"
        # and "your key is for a different workspace".
        try:
            detail = exc.read().decode()[:500]
        except Exception:  # noqa: BLE001 - diagnosis must not raise
            detail = "<body unreadable>"
        return None, f"HTTP {exc.code}: {detail}"
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return None, str(exc)


def _call(query: str, variables: dict) -> dict | None:
    if not is_configured():
        logger.warning("linear: no API key or team id configured, skipping call")
        return None

    # A key pasted from a browser very often carries a trailing newline, which
    # is invisible in the Railway UI and rejected as a bad credential.
    key = settings.LINEAR_API_KEY.strip()
    payload = json.dumps({"query": query, "variables": variables}).encode()

    body, error = _post(payload, key)

    # Personal API keys go in raw; OAuth access tokens need the Bearer prefix.
    # Rather than ask which kind is configured, try the other one once. This
    # only fires on an auth rejection, so it costs nothing in the normal case.
    if body is None and error and error.startswith(("HTTP 401", "HTTP 403")):
        logger.warning("linear: %s -- retrying with a Bearer prefix", error)
        body, error = _post(payload, f"Bearer {key}")

    if body is None:
        logger.warning("linear: call failed: %s", error)
        return None

    # GraphQL answers 200 with an errors array, so a happy status code proves
    # nothing on its own.
    if body.get("errors"):
        logger.warning("linear: API returned errors: %s", body["errors"])
        return None
    return body.get("data")


def create_support_issue(*, title: str, description: str) -> tuple[str, str] | None:
    """Open an issue on the support team. Returns (id, identifier), or None."""
    issue_input = {
        "teamId": settings.LINEAR_SUPPORT_TEAM_ID,
        "title": title[:255],
        "description": description,
    }
    if settings.LINEAR_SUPPORT_LABEL_ID:
        issue_input["labelIds"] = [settings.LINEAR_SUPPORT_LABEL_ID]
    if settings.LINEAR_SUPPORT_PROJECT_ID:
        issue_input["projectId"] = settings.LINEAR_SUPPORT_PROJECT_ID

    data = _call(_CREATE_ISSUE, {"input": issue_input})
    if not data:
        return None

    result = data.get("issueCreate") or {}
    issue = result.get("issue") or {}
    if not result.get("success") or not issue.get("id"):
        logger.warning("linear: issue creation reported no success: %s", result)
        return None
    return issue["id"], issue.get("identifier", "")


def fetch_statuses(issue_ids: list[str]) -> dict[str, str]:
    """Map Linear issue id to one of our four statuses.

    Ids missing from the answer are simply absent from the result, so callers
    keep the last status they stored rather than inventing one.
    """
    if not issue_ids:
        return {}

    data = _call(_ISSUE_STATES, {"ids": issue_ids})
    if not data:
        return {}

    statuses: dict[str, str] = {}
    for node in (data.get("issues") or {}).get("nodes") or []:
        state_type = (node.get("state") or {}).get("type")
        mapped = _STATE_TYPE_TO_STATUS.get(state_type)
        if node.get("id") and mapped:
            statuses[node["id"]] = mapped
    return statuses

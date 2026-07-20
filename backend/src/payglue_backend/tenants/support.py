# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Support requests: store, file in Linear, confirm by email, read status back.

The order matters. The row is written first and everything after it is
best-effort, because a request we have is a request we can answer, while a
request lost to a Linear timeout is gone for good.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from payglue_backend.authn.lifecycle_emails import _send_branded
from payglue_backend.tenants import linear
from payglue_backend.tenants.models import SupportRequest, Tenant

logger = logging.getLogger(__name__)

TOPIC_LABELS = {
    "integration": "Setting up an integration",
    "billing": "Billing or plans",
    "bug": "Something is broken",
    "feature": "Feature request",
    "account": "Account or team",
    "other": "Something else",
}

# Statuses we never re-read from Linear. Once an issue is resolved or closed
# it stays that way for the customer, so a later re-open in Linear (which we
# do for our own bookkeeping) does not reopen a ticket they consider done.
_TERMINAL = {SupportRequest.STATUS_DONE, SupportRequest.STATUS_CANCELLED}


def _issue_description(request: SupportRequest, tenant: Tenant) -> str:
    topic = TOPIC_LABELS.get(request.topic, request.topic or "unspecified")
    return (
        f"**From:** {request.name or 'not given'} <{request.email}>\n"
        f"**Publication:** `{tenant.slug}`\n"
        f"**Topic:** {topic}\n\n"
        f"---\n\n{request.message}"
    )


def create_support_request(
    *,
    tenant: Tenant,
    email: str,
    name: str,
    topic: str,
    message: str,
) -> SupportRequest:
    request = SupportRequest.objects.create(
        tenant=tenant,
        email=email,
        name=name,
        topic=topic,
        message=message,
    )

    topic_label = TOPIC_LABELS.get(topic, "Support")
    filed = linear.create_support_issue(
        title=f"[{topic_label}] {tenant.slug}: {message.strip()[:80]}",
        description=_issue_description(request, tenant),
    )
    if filed:
        request.linear_issue_id, request.linear_identifier = filed
        request.save(update_fields=["linear_issue_id", "linear_identifier"])

    _notify(request, tenant)
    return request


def _notify(request: SupportRequest, tenant: Tenant) -> None:
    """Confirmation to the customer, and the request itself to us.

    Wrapped because an email provider hiccup must not turn a stored request
    into a 500 that invites the customer to send it a second time.
    """
    try:
        _send_branded(
            f"We have your request ({request.reference})",
            f"Hi{' ' + request.name if request.name else ''},\n\n"
            f"Thanks for writing in. Your request is logged as {request.reference}, "
            "and quoting that reference in any reply keeps everything in one place.\n\n"
            "You can follow its status under Settings, Support in your dashboard. "
            "We answer by email, usually within one working day.\n\n"
            "__\nCheers,\nPayGlue - Team",
            [request.email],
        )
    except Exception:  # noqa: BLE001 - the request is already safely stored
        logger.exception("support: confirmation email failed for %s", request.pk)

    try:
        _send_branded(
            f"Support: {request.reference} from {tenant.slug}",
            f"{request.name or 'Someone'} <{request.email}> wrote in about "
            f"{TOPIC_LABELS.get(request.topic, 'something else').lower()}.\n\n"
            f"Publication: {tenant.slug}\n\n"
            f"---\n\n{request.message}",
            [settings.INTERNAL_ADMIN_EMAIL],
        )
    except Exception:  # noqa: BLE001
        logger.exception("support: internal notification failed for %s", request.pk)


def sync_statuses(requests: list[SupportRequest]) -> list[SupportRequest]:
    """Refresh statuses from Linear in one call, and persist what changed.

    Called when the customer opens the support page. That is rare enough to
    not need caching, and it means André changing a status in Linear shows up
    without any webhook to maintain.
    """
    pending = [
        r for r in requests if r.linear_issue_id and r.status not in _TERMINAL
    ]
    if not pending:
        return requests

    statuses = linear.fetch_statuses([r.linear_issue_id for r in pending])
    now = timezone.now()
    changed = []
    for request in pending:
        new_status = statuses.get(request.linear_issue_id)
        if not new_status:
            continue
        request.status_synced_at = now
        if new_status != request.status:
            request.status = new_status
        changed.append(request)

    if changed:
        SupportRequest.objects.bulk_update(changed, ["status", "status_synced_at"])
    return requests

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Support requests: store, open a helpdesk ticket, read its status back.

The order matters. The row is written first and everything after it is
best-effort, because a request we have is a request we can answer, while a
request lost to a helpdesk timeout is gone for good. Without a helpdesk, or
when it cannot be reached, the request is confirmed and forwarded by email.
"""
from __future__ import annotations

import logging
from email.utils import formataddr

from django.conf import settings
from django.utils import timezone

from payglue_backend.authn.lifecycle_emails import _send_branded
# The helpdesk client is an add-on of the hosted product and is not part of
# every build. Without it, support works by email alone.
try:
    from payglue_backend.tenants import helpdesk
except ImportError:  # pragma: no cover - depends on the build
    helpdesk = None
from payglue_backend.tenants.models import SupportRequest, TenantMembership, Tenant

logger = logging.getLogger(__name__)

TOPIC_LABELS = {
    "integration": "Setting up an integration",
    "billing": "Billing or plans",
    "bug": "Something is broken",
    "feature": "Feature request",
    "account": "Account or team",
    "other": "Something else",
}

# Statuses we never re-read from the helpdesk. Once a ticket is resolved or
# closed it stays that way for the customer, so a later re-open on our side
# (which we do for our own bookkeeping) never reopens a ticket they consider
# done.
_TERMINAL = {SupportRequest.STATUS_DONE, SupportRequest.STATUS_CANCELLED}


def _owner_email(tenant: Tenant) -> str:
    """The address of whoever owns the workspace, or empty."""
    membership = (
        tenant.memberships.filter(role=TenantMembership.Role.OWNER)
        .select_related("user_profile")
        .first()
    )
    return getattr(getattr(membership, "user_profile", None), "email", "") or ""


def _service_pin(tenant: Tenant):
    """The newest PIN that is still valid, or None. Revoked and expired ones
    do not count: both mean the customer withdrew or let lapse their consent."""
    return (
        tenant.service_pins.filter(revoked_at__isnull=True, expires_at__gt=timezone.now())
        .order_by("-created_at")
        .first()
    )


def _summary(message: str, limit: int = 80) -> str:
    """The issue title, from the customer's own words.

    Cutting the raw message at a fixed length pulled line breaks into the
    title, and the issue tracker we used then rendered them, so the start of a
    second paragraph looked like a heading. Only the opening paragraph is used now, whitespace
    collapsed, and the cut lands on a word boundary rather than mid-word. A
    title is the opening thought, not a run-on across the whole message.
    """
    first = message.strip().split("\n\n", 1)[0]
    text = " ".join(first.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    spaced = cut.rsplit(" ", 1)[0]
    # A single word longer than the limit has no boundary to fall back on.
    return (spaced if len(spaced) >= limit // 2 else cut) + "..."


def create_support_request(
    *,
    tenant: Tenant,
    email: str,
    name: str,
    topic: str,
    message: str,
    subject: str = "",
    account_email: str = "",
) -> SupportRequest:
    request = SupportRequest.objects.create(
        tenant=tenant,
        email=email,
        account_email=account_email,
        name=name,
        topic=topic,
        subject=subject,
        message=message,
    )

    # The customer's own words when they gave us any, otherwise the opening
    # line of the message. Deriving a summary is always guesswork, so it is the
    # fallback rather than the rule.
    headline = subject.strip() or _summary(message)

    # PG-360: with a helpdesk configured the request becomes a ticket there,
    # and the helpdesk confirms, answers and reports status to the customer.
    # Without one, or when it cannot be reached, the request is confirmed and
    # forwarded by email, so it is never left without an answer route.
    if helpdesk is not None and helpdesk.is_configured():
        filed = helpdesk.create_support_ticket(
            title=headline,
            message=message,
            topic=topic,
            email=email,
            name=name,
            internal_note=_internal_context(request, tenant)
            + f"Topic: {TOPIC_LABELS.get(topic, 'unspecified')}\n"
            + f"Our reference: {request.reference}\n",
        )
        if filed:
            request.tracker_issue_id, request.tracker_identifier = filed
            request.save(update_fields=["tracker_issue_id", "tracker_identifier"])
            return request

    _notify(request, tenant)
    return request


def _internal_context(request: SupportRequest, tenant: Tenant) -> str:
    """The block only we see: who really wrote, and what we may do.

    Plain text, because this is the mail that lands in our own inbox and gets
    read on a phone as often as anywhere else.
    """
    lines = [f"Publication: {tenant.slug}"]
    if request.account_email and request.account_email.lower() != request.email.lower():
        lines.append(f"Submitted by: {request.account_email}")
    owner = _owner_email(tenant)
    if owner and owner.lower() not in {request.email.lower(), (request.account_email or "").lower()}:
        lines.append(f"Account owner: {owner}")
    pin = _service_pin(tenant)
    if pin is None:
        lines.append("Service PIN: none, read and debug only")
    else:
        until = timezone.localtime(pin.expires_at).strftime("%d.%m.%Y %H:%M")
        lines.append(f"Service PIN: {pin.code}, valid until {until}, active changes authorised")
    return "\n".join(lines) + "\n"


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
            f"{_internal_context(request, tenant)}\n"
            f"---\n\n{request.message}",
            [settings.INTERNAL_ADMIN_EMAIL],
            # Both From and To are our own team address, so Reply would answer
            # ourselves. Point it at the customer instead, name included, so
            # replying from the mail client just works.
            reply_to=[formataddr((request.name or "", request.email))],
        )
    except Exception:  # noqa: BLE001
        logger.exception("support: internal notification failed for %s", request.pk)


def sync_statuses(requests: list[SupportRequest]) -> list[SupportRequest]:
    """Refresh statuses from the helpdesk and persist what changed.

    Called when the customer opens the support page, and by the
    sync_support_statuses cron. The helpdesk mails status changes to the
    customer itself, so nothing is sent from here.

    Requests filed before the helpdesk carry an id from the issue tracker we
    used then. That tracker is gone, so they keep the status they had.
    """
    if helpdesk is None:
        return requests
    pending = [
        r
        for r in requests
        if helpdesk.owns(r.tracker_issue_id) and r.status not in _TERMINAL
    ]
    if not pending:
        return requests

    statuses = helpdesk.fetch_statuses([r.tracker_issue_id for r in pending])
    now = timezone.now()
    changed = []
    for request in pending:
        new_status = statuses.get(request.tracker_issue_id)
        if not new_status:
            continue
        request.status_synced_at = now
        request.status = new_status
        changed.append(request)

    if changed:
        SupportRequest.objects.bulk_update(changed, ["status", "status_synced_at"])
    return requests

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Support requests: store, file an issue, confirm by email, read status back.

The order matters. The row is written first and everything after it is
best-effort, because a request we have is a request we can answer, while a
request lost to a tracker timeout is gone for good.
"""
from __future__ import annotations

import html
import logging
from email.utils import formataddr

from django.conf import settings
from django.utils import timezone

from payglue_backend.authn.lifecycle_emails import _send_branded
from payglue_backend.tenants import tracker
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

# The label each topic gets in the tracker. Five of the six are the topic key
# itself; "other" would be a poor label name on a board, so it reads general.
TOPIC_LABEL_NAMES = {
    "integration": "integration",
    "billing": "billing",
    "bug": "bug",
    "feature": "feature",
    "account": "account",
    "other": "general",
}

# Statuses we never re-read from the tracker. Once an issue is resolved or
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


def _service_pin_line(tenant: Tenant) -> str:
    """What support is allowed to do, spelled out on the ticket.

    A PIN is the customer consenting to active changes; without one we may read
    and debug and nothing else. That is the sentence somebody needs before
    touching an account, and it should not have to be looked up elsewhere.

    Internal only. The customer sees their PIN in the dashboard already, and a
    consent code has no business sitting in a mailbox longer than it must.
    """
    pin = _service_pin(tenant)
    if pin is None:
        return "<strong>Service PIN:</strong> none, read and debug only"
    until = timezone.localtime(pin.expires_at).strftime("%d.%m.%Y %H:%M")
    return (
        f"<strong>Service PIN:</strong> <code>{html.escape(pin.code)}</code>, "
        f"valid until {until}, active changes authorised"
    )


def _issue_description(request: SupportRequest, tenant: Tenant) -> str:
    """The issue body, as HTML.

    The tracker stores descriptions as HTML and renders markdown literally, so
    a `**bold**` here would reach us as four asterisks. Everything the customer
    typed is escaped: their message is arbitrary text that lands in a page we
    open ourselves, and it may well contain a snippet of their own theme.
    """
    topic = TOPIC_LABELS.get(request.topic, request.topic or "unspecified")
    name = html.escape(request.name or "not given")
    slug = html.escape(tenant.slug)
    # Blank lines become paragraphs, single ones stay inside their paragraph.
    body = "".join(
        f"<p>{html.escape(block).replace(chr(10), '<br>')}</p>"
        for block in request.message.strip().split("\n\n")
        if block.strip()
    )

    # Contact goes first because it answers the first question anybody opening
    # this ticket has: where does a reply go. The tracker's email intake takes
    # that address from the API call rather than from this text, so the order
    # is for the human reading it, not for a parser.
    lines = [f"<strong>Contact:</strong> {name} &lt;{html.escape(request.email)}&gt;"]
    if request.account_email and request.account_email.lower() != request.email.lower():
        # Only when it differs. Repeating the same address twice is noise, and
        # a difference is exactly the thing worth seeing.
        lines.append(
            f"<strong>Submitted by:</strong> {html.escape(request.account_email)}"
        )
    if request.subject:
        lines.append(f"<strong>Subject:</strong> {html.escape(request.subject)}")
    lines.append(f"<strong>Publication:</strong> <code>{slug}</code>")
    owner = _owner_email(tenant)
    if owner and owner.lower() not in {request.email.lower(), (request.account_email or "").lower()}:
        # Matters once a workspace has several people in it: the person writing
        # is not necessarily the one who can decide anything.
        lines.append(f"<strong>Account owner:</strong> {html.escape(owner)}")
    lines.append(f"<strong>Topic:</strong> {html.escape(topic)}")
    lines.append(_service_pin_line(tenant))

    return f"<p>{'<br>'.join(lines)}</p><hr>{body}"


def _summary(message: str, limit: int = 80) -> str:
    """The issue title, from the customer's own words.

    Cutting the raw message at a fixed length pulled line breaks into the
    title, and the tracker rendered them, so the start of a second paragraph
    looked like a heading. Only the opening paragraph is used now, whitespace
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

    topic_label = TOPIC_LABELS.get(topic, "Support")
    # The customer's own words when they gave us any, otherwise the opening
    # line of the message. Deriving a summary is always guesswork, so it is the
    # fallback rather than the rule.
    headline = subject.strip() or _summary(message)
    # No category chosen still gets a label. The topic is deliberately optional,
    # because somebody whose problem fits no box still has a problem, but an
    # unlabelled ticket cannot be filtered out of a board later.
    label = TOPIC_LABEL_NAMES.get(topic) or TOPIC_LABEL_NAMES["other"]
    filed = tracker.create_support_issue(
        title=f"[{topic_label}] {tenant.slug}: {headline}",
        description_html=_issue_description(request, tenant),
        label_names=[label],
    )
    if filed:
        request.tracker_issue_id, request.tracker_identifier = filed
        request.save(update_fields=["tracker_issue_id", "tracker_identifier"])
        # Hands the reply address to the tracker so an answer can be written
        # straight on the issue. Ours arrive over the API rather than by mail,
        # and without this the outward path stays shut (PG-266).
        tracker.link_requester_email(request.tracker_issue_id, email=email, name=name)

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


# Customer-facing wording per status, matching what the dashboard shows.
_STATUS_LABELS = dict(SupportRequest.STATUS_CHOICES)

# What the new status means for the customer, in one sentence. Keyed by the
# status the request just moved TO; a transition without an entry (back to
# "open", say) is persisted but not emailed -- an "update" mail that only says
# "still open" would read as noise.
_STATUS_MAIL_LINES = {
    SupportRequest.STATUS_IN_PROGRESS: "We are on it. You will hear from us by email as soon as there is something to share.",
    SupportRequest.STATUS_DONE: "We consider this resolved. If anything still looks off, just reply to the email thread and we will pick it right back up.",
    SupportRequest.STATUS_CANCELLED: "This request has been closed. If that comes as a surprise, reply to the email thread and we will take another look.",
}


def _notify_status_change(request: SupportRequest) -> None:
    """Tell the customer their ticket moved, from noreply@ (a pure system
    notice -- replies belong in the human email thread, which the body says).

    Best-effort like every mail here: the status change itself is already
    persisted, a mail hiccup must not undo or block that.
    """
    line = _STATUS_MAIL_LINES.get(request.status)
    if not line:
        return
    label = _STATUS_LABELS.get(request.status, request.status)
    try:
        _send_branded(
            f"Your request {request.reference} is now: {label}",
            f"Hi{' ' + request.name if request.name else ''},\n\n"
            f"Quick update on your support request {request.reference}: "
            f"its status changed to {label}.\n\n"
            f"{line}\n\n"
            "You can always check the current status under Settings, Support "
            "in your dashboard.\n\n"
            "__\nCheers,\nPayGlue - Team",
            [request.email],
            from_email=settings.SYSTEM_NOTICE_FROM_EMAIL,
        )
    except Exception:  # noqa: BLE001
        logger.exception("support: status change email failed for %s", request.pk)


def sync_statuses(requests: list[SupportRequest]) -> list[SupportRequest]:
    """Refresh statuses from the tracker and persist what changed.

    Called when the customer opens the support page, and by the
    sync_support_statuses cron so a status change reaches the customer by
    email without them having to look. Either path persists a transition
    exactly once, so the notification cannot double-send.
    """
    pending = [
        r for r in requests if r.tracker_issue_id and r.status not in _TERMINAL
    ]
    if not pending:
        return requests

    statuses = tracker.fetch_statuses([r.tracker_issue_id for r in pending])
    now = timezone.now()
    changed = []
    transitioned = []
    for request in pending:
        new_status = statuses.get(request.tracker_issue_id)
        if not new_status:
            continue
        request.status_synced_at = now
        if new_status != request.status:
            request.status = new_status
            transitioned.append(request)
        changed.append(request)

    if changed:
        SupportRequest.objects.bulk_update(changed, ["status", "status_synced_at"])
    # Only after the persist: a mail about a change that failed to save would
    # promise a status the dashboard then contradicts.
    for request in transitioned:
        _notify_status_change(request)
    return requests

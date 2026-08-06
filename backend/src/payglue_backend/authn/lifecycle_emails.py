# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-148: sends admin-editable retention/lifecycle emails to PayGlue's own
paying customers (tenant owners) through Resend. Deliberately not Brevo
(mentioned in the original ticket, but never actually wired up anywhere in
this codebase) or Resend's own workflow/automation product (paid add-on) --
the trigger logic lives here instead. Transport is Resend's HTTPS API, not
SMTP: Railway blocks outbound SMTP ports, see core/email_backend.py.

Fails safe, not loud: a missing or disabled LifecycleEmailTemplate for a
given trigger just means nothing gets sent, no exception, no retry needed.
"""
import html as _html
import logging
import re
from string import Template

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from payglue_backend.tenants.models import BillingAccount, LifecycleEmailLog, LifecycleEmailTemplate
from payglue_backend.core.public_urls import app_url

logger = logging.getLogger(__name__)

# PG-202: wrap every lifecycle email in PayGlue's branded HTML shell (the dark
# card from the Supabase signup email) so they stop looking like raw plain text.
# The editable template body stays plain text -- words are edited in the admin,
# never HTML -- and this renders it into the shell at send time. The plain-text
# body is still sent as the fallback part for text-only clients.
# Served by the dashboard, so it only resolves once the dashboard address is
# configured. Empty means the shell renders without a logo rather than with a
# broken image pointing at somebody else's server (PG-238).
_EMAIL_LOGO_PATH = "email-icon.png"
_URL_RE = re.compile(r"https?://[^\s<]+")

_EMAIL_SHELL = """\
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{subject}</title></head>
<body style="margin:0;padding:0;background-color:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#0f172a;padding:48px 16px;">
    <tr><td align="center">
      <table width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;">
        <tr><td style="padding-bottom:32px;">
          <table cellpadding="0" cellspacing="0"><tr>
            <td style="padding-right:10px;vertical-align:middle;">
              <img src="{logo}" alt="" width="28" height="28" style="display:block;border-radius:6px;" />
            </td>
            <td style="vertical-align:middle;">
              <span style="font-size:18px;font-weight:800;letter-spacing:-0.3px;">
                <span style="color:#818cf8;">Pay</span><span style="color:#ffffff;">Glue</span>
              </span>
            </td>
          </tr></table>
        </td></tr>
        <tr><td style="background-color:#1e293b;border-radius:16px;padding:40px;border:1px solid #334155;">
          {content}
        </td></tr>
        <tr><td style="padding-top:28px;">
          <p style="margin:0;font-size:12px;color:#334155;">&copy; 2026 PayGlue &middot; <a href="https://payglue.io" style="color:#475569;text-decoration:none;">payglue.io</a></p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _render_branded_email(subject: str, body: str) -> str:
    """Render a plain-text email body into the branded HTML shell. Blank-line
    separated paragraphs become <p>, single newlines <br>, and bare URLs become
    links -- so an admin only ever types plain text but the email looks designed."""
    blocks = []
    for para in body.strip().split("\n\n"):
        escaped = _html.escape(para.strip())
        escaped = _URL_RE.sub(
            lambda m: f'<a href="{m.group(0)}" style="color:#818cf8;text-decoration:none;">{m.group(0)}</a>',
            escaped,
        )
        escaped = escaped.replace("\n", "<br />")
        blocks.append(
            f'<p style="margin:0 0 16px;font-size:15px;color:#cbd5e1;line-height:1.7;">{escaped}</p>'
        )
    return _EMAIL_SHELL.format(
        subject=_html.escape(subject),
        logo=app_url(_EMAIL_LOGO_PATH),
        content="".join(blocks),
    )


def _send_branded(
    subject: str,
    body: str,
    recipients: list[str],
    reply_to: list[str] | None = None,
    from_email: str | None = None,
) -> None:
    """Branded HTML part attached; plain text stays the fallback.

    `reply_to` is for the notifications we send to ourselves. The support alert
    goes from team@ to team@, so without it, hitting Reply in a mail client
    answers us instead of the customer who wrote in. The Resend backend
    forwards the header and its staging redirect leaves it alone.

    `from_email` lets pure system notices come from noreply@ instead of the
    default team@, which invites replies (see SYSTEM_NOTICE_FROM_EMAIL).

    Blank recipients are dropped, and with none left this does nothing. Every
    internal notice addresses settings.INTERNAL_ADMIN_EMAIL, which is empty
    unless an installation configures it (PG-239), and handing the mail API an
    empty address would turn "nobody wants these notices" into a logged error
    on every run.
    """
    recipients = [r for r in recipients if r and r.strip()]
    if not recipients:
        return
    message = EmailMultiAlternatives(
        subject,
        body,
        from_email or settings.DEFAULT_FROM_EMAIL,
        recipients,
        reply_to=reply_to or None,
    )
    message.attach_alternative(_render_branded_email(subject, body), "text/html")
    message.send()


# The closing every customer-facing email ends with. Kept in one place so the
# fallback copy below can't drift apart from what the seeded templates say.
_SIGN_OFF = "__\nCheers,\nPayGlue - Team"


def _send_templated(
    trigger: str,
    context: dict[str, str],
    recipients: list[str],
    fallback_subject: str,
    fallback_body: str,
) -> bool:
    """Render the admin-editable template for `trigger` and send it.

    Shared by every non-subscription trigger (ownership transfers, Ghost
    alerts). Disabling the template in the admin silences the mail; a missing
    row falls back to the built-in copy so an alert can't go dark by accident.
    Each recipient gets their own send, so nobody's address shows up in
    somebody else's To header. Fail-safe: failures are logged, never raised.
    Returns True only if every recipient was sent to."""
    template = LifecycleEmailTemplate.objects.filter(trigger=trigger).first()
    if template is not None and not template.enabled:
        return False
    subject_tpl = template.subject if template is not None else fallback_subject
    body_tpl = template.body if template is not None else fallback_body

    subject = Template(subject_tpl).safe_substitute(context)
    body = Template(body_tpl).safe_substitute(context)

    sent_all = True
    # dict.fromkeys dedups while keeping order -- the same person can legitimately
    # be two parties in one transfer (e.g. the owner requesting it themselves).
    for recipient in dict.fromkeys(r for r in recipients if r):
        try:
            _send_branded(subject, body, [recipient])
        except Exception:
            logger.exception("Failed to send %s email to %s", trigger, recipient)
            sent_all = False
    return sent_all


def send_lifecycle_email(billing_account: BillingAccount, trigger: str) -> bool:
    """Renders and sends the configured template for `trigger`, then logs
    it. Returns False (no-op) if no enabled template exists for this
    trigger -- callers don't need to check first."""
    template = LifecycleEmailTemplate.objects.filter(trigger=trigger, enabled=True).first()
    if template is None:
        return False

    context = {
        "email": billing_account.owner.email,
        "plan": billing_account.plan.name,
    }
    # safe_substitute, not substitute -- a typo'd $placeholder in an
    # admin-edited template must never crash the send, just pass through
    # literally so it's obviously wrong in the sent email instead.
    subject = Template(template.subject).safe_substitute(context)
    body = Template(template.body).safe_substitute(context)

    try:
        _send_branded(subject, body, [billing_account.owner.email])
    except Exception:
        logger.exception(
            "Failed to send lifecycle email (trigger=%s) to %s", trigger, billing_account.owner.email
        )
        return False

    LifecycleEmailLog.objects.create(billing_account=billing_account, trigger=trigger)
    return True


def notify_admin_review_needed(billing_account: BillingAccount, reason: str) -> None:
    """PG-190: alerts the operator (settings.INTERNAL_ADMIN_EMAIL) when a
    subscription's Creem status can't be classified as either "still fine"
    or "confirmed canceled" -- e.g. past_due/unpaid/paused, or the raw
    status fetch itself failed. Only a human can tell a temporary payment
    retry apart from a real problem by checking Creem directly, so nothing
    here starts the deletion clock. Deliberately not a LifecycleEmailTemplate
    (this isn't customer-facing, doesn't need admin-editable copy) and not
    logged to LifecycleEmailLog (that's a customer-email audit trail; the
    caller dedups this via BillingAccount.needs_admin_review itself, only
    calling this on the False -> True transition). Best-effort: a failure
    here is logged, not raised -- it must never block the poll command."""
    subject = f"PayGlue: unclear Creem status for {billing_account.owner.email} ({reason})"
    body = (
        f"Account: {billing_account.owner.email}\n"
        f"Plan: {billing_account.plan.name}\n"
        f"Creem status: {reason}\n\n"
        "This could not be read as a cancellation either way (payment failed, "
        "paused, or the status fetch itself did not come back). Check it in "
        "Creem directly. The 30-day deletion window only starts once the "
        "status is unambiguously 'canceled'."
    )
    try:
        _send_branded(subject, body, [settings.INTERNAL_ADMIN_EMAIL])
    except Exception:
        logger.exception(
            "Failed to send admin-review notification for %s", billing_account.owner.email
        )


def notify_admin_license_redeemed(license_code, email: str) -> None:
    """Tell us when somebody signs up with one of our own PAYGLUE invite codes.

    A Creem purchase already announces itself by email; a code we handed out on
    Reddit or in a DM did not, so those signups landed silently and we only saw
    them by chance in the admin. Same shape as the notice above: not
    customer-facing, not a LifecycleEmailTemplate, and best-effort -- a signup
    must never fail because a notification could not be sent.

    Called once per fresh redemption. Retries of the same redemption are
    idempotent upstream and never reach this.
    """
    used = license_code.activation_count
    cap = license_code.max_activations
    remaining = "unlimited" if cap is None else f"{max(cap - used, 0)} of {cap} left"
    duration = (
        "never expires"
        if license_code.access_days == 0
        else f"{license_code.access_days} days"
    )
    # Address in the subject on purpose: it makes the mail searchable in the
    # inbox, which is how you find the account again weeks later.
    subject = f"New PayGlue signup: {email} (invite code {license_code.code})"
    body = (
        f"{email} just signed up with one of our own codes.\n\n"
        f"User: {email}\n"
        f"Code: {license_code.code}\n"
        f"Label: {license_code.label or '(none)'}\n"
        f"Plan: {license_code.plan.name}\n"
        f"Access: {duration}\n"
        f"Activations: {used} used, {remaining}\n\n"
        "No payment involved, this is a tester on a code we gave out."
    )
    try:
        _send_branded(subject, body, [settings.INTERNAL_ADMIN_EMAIL])
    except Exception:
        logger.exception("Failed to send license-redeemed notification for %s", email)


def notify_admin_account_deleted(
    email: str, tenants_deleted: int, tenants_left: int
) -> None:
    """Tell us when somebody deletes their whole account, not just a tenant.

    The customer gets their own receipt (send_account_deleted_email); this is
    the other half, so a departure isn't something we notice by chance. Counts
    come from the caller because the rows are gone by the time this runs.

    Same shape as the other admin notices: hard-wired copy, no
    LifecycleEmailTemplate, no LifecycleEmailLog, best-effort. The account is
    already deleted when this fires -- throwing here would turn a successful
    deletion into a 500 for something that did succeed.
    """
    subject = f"PayGlue account deleted: {email}"
    body = (
        f"{email} deleted their entire PayGlue account, not just a workspace.\n\n"
        f"User: {email}\n"
        f"Workspaces deleted with them: {tenants_deleted}\n"
        f"Workspaces they only left (other owners remain): {tenants_left}\n\n"
        "Self-service deletion, so it is already done and cannot be undone. "
        "Worth a look at why if this person was a paying customer."
    )
    try:
        _send_branded(subject, body, [settings.INTERNAL_ADMIN_EMAIL])
    except Exception:
        logger.exception("Failed to send account-deleted notification for %s", email)


# Fallback copy used only if the admin-editable GHOST_DELIVERY_FAILING template
# row is somehow missing entirely (it is seeded by migration). Keeps the alert
# working even then -- an alert going silent is the exact failure we're guarding
# against. If the template is *disabled* in the admin, that's respected (no
# send); this fallback is only for the no-row edge.
_GHOST_ALERT_FALLBACK_SUBJECT = "PayGlue: Your Ghost connection is failing"
_GHOST_ALERT_FALLBACK_BODY = (
    "Hi,\n\n"
    "Access delivery to your Ghost site ($tenant) has been failing repeatedly. "
    "That means new purchases are NOT being unlocked automatically right now.\n\n"
    "Most common cause: your Ghost Admin API key was rotated or has expired, or "
    "your Ghost instance is temporarily unreachable.\n\n"
    "Please check your Ghost connection in PayGlue:\n"
    "$url\n\n"
    "There you can update your Ghost credentials and re-test with 'Run health "
    "check'. Once the connection works again, pending events are re-delivered "
    "automatically.\n\n" + _SIGN_OFF
)


# Dummy placeholder values so any template (subscription or ghost-alert) renders
# in a test send. `email` is overridden with the real recipient at send time.
def _test_render_context() -> dict[str, str]:
    """Placeholder values for the admin's "send me a test" button.

    A function rather than a module-level dict because "url" depends on
    PUBLIC_APP_BASE_URL. Evaluated at import time it would freeze whatever the
    setting happened to be when Django loaded, which for a worker started
    before its configuration is the empty string, permanently.
    """
    return {
        "email": "you@example.com",
        "plan": "Studio",
        "tenant": "your-publication",
        "url": app_url("/t/your-publication/connection/ghost"),
        "new_owner": "teammate@example.com",
        "previous_owner": "you@example.com",
    }


def send_test_lifecycle_email_error(template: LifecycleEmailTemplate, recipient: str) -> str:
    """PG-191: render `template` with dummy placeholder values and send it to
    `recipient` (the admin themselves) so subject/body/placeholders can be
    eyeballed before a template is switched on. Sends regardless of the
    template's `enabled` flag (it's an explicit test), prefixes the subject
    with [Test], and deliberately does NOT write a LifecycleEmailLog -- that
    audit trail is for real customer sends only.

    Returns "" on success or the error message (e.g. the raw SMTP failure) so
    the admin can show exactly why a test send failed -- typically a
    RESEND_API_KEY / verified-sender-domain problem -- instead of a generic
    'failed'. Never raises."""
    context = {**_test_render_context(), "email": recipient}
    subject = "[Test] " + Template(template.subject).safe_substitute(context)
    body = Template(template.body).safe_substitute(context)
    try:
        _send_branded(subject, body, [recipient])
        return ""
    except Exception as exc:
        logger.exception(
            "Failed to send test email (trigger=%s) to %s", template.trigger, recipient
        )
        return str(exc) or exc.__class__.__name__


def send_test_lifecycle_email(template: LifecycleEmailTemplate, recipient: str) -> bool:
    """Bool wrapper (used by the bulk list action). True on success."""
    return send_test_lifecycle_email_error(template, recipient) == ""


_OWNER_TRANSFER_FALLBACK_SUBJECT = "PayGlue: Ownership transfer requested for $tenant"
_OWNER_TRANSFER_FALLBACK_BODY = (
    "Hi,\n\n"
    "Someone requested to transfer ownership of your publication $tenant to "
    "$new_owner.\n\n"
    "For security, the transfer only takes effect once you confirm it yourself. "
    "Please log in to PayGlue and confirm or reject it under Team:\n$url\n\n"
    "If this wasn't you, reject the transfer and check who has access to your "
    "account. Your billing stays with you -- after you confirm, you become the "
    "billing admin.\n\n" + _SIGN_OFF
)

_OWNER_PROPOSED_FALLBACK_SUBJECT = "PayGlue: You've been proposed as the owner of $tenant"
_OWNER_PROPOSED_FALLBACK_BODY = (
    "Hi,\n\n"
    "You've been proposed as the new owner of the publication $tenant.\n\n"
    "Nothing has changed yet. $previous_owner still has to confirm the transfer, "
    "and you'll get another email as soon as that happens.\n\n"
    "As the owner you would manage the team and the publication itself. Billing "
    "stays with $previous_owner, so nothing about the subscription moves to you.\n\n"
    "You can follow the status here:\n$url\n\n" + _SIGN_OFF
)

_OWNER_CONFIRMED_FALLBACK_SUBJECT = "PayGlue: $new_owner is now the owner of $tenant"
_OWNER_CONFIRMED_FALLBACK_BODY = (
    "Hi,\n\n"
    "The ownership transfer for $tenant is complete. $new_owner is now the owner.\n\n"
    "$previous_owner keeps access as billing admin, so the subscription and all "
    "invoices stay exactly where they were.\n\n"
    "You can review the team here:\n$url\n\n"
    "If you weren't expecting this change, reply to this email right away.\n\n" + _SIGN_OFF
)

_OWNER_REJECTED_FALLBACK_SUBJECT = "PayGlue: The ownership transfer for $tenant was called off"
_OWNER_REJECTED_FALLBACK_BODY = (
    "Hi,\n\n"
    "The requested ownership transfer of $tenant to $new_owner will not go ahead. "
    "It was either rejected by the current owner or cancelled before it was "
    "confirmed.\n\n"
    "Nothing changed. $previous_owner is still the owner and every role stayed as "
    "it was.\n\n"
    "You can review the team here:\n$url\n\n" + _SIGN_OFF
)


def _transfer_context(
    current_owner_email: str, new_owner_email: str, tenant_slug: str
) -> dict[str, str]:
    """Placeholders shared by all four ownership-transfer emails."""
    return {
        "email": current_owner_email,
        "new_owner": new_owner_email,
        "previous_owner": current_owner_email,
        "tenant": tenant_slug,
        "url": app_url(f"/t/{tenant_slug}/team"),
    }


def send_owner_transfer_request_email(
    current_owner_email: str, new_owner_email: str, tenant_slug: str
) -> bool:
    """PG-182: emails the current owner that an ownership transfer to
    `new_owner_email` was requested, asking them to confirm/reject it in the
    dashboard. Admin-editable via the OWNER_TRANSFER_REQUESTED
    LifecycleEmailTemplate (placeholders: $email, $new_owner, $previous_owner,
    $tenant, $url)."""
    return _send_templated(
        LifecycleEmailTemplate.Trigger.OWNER_TRANSFER_REQUESTED,
        _transfer_context(current_owner_email, new_owner_email, tenant_slug),
        [current_owner_email],
        _OWNER_TRANSFER_FALLBACK_SUBJECT,
        _OWNER_TRANSFER_FALLBACK_BODY,
    )


def send_owner_transfer_proposed_email(
    current_owner_email: str, new_owner_email: str, tenant_slug: str
) -> bool:
    """PG-182 follow-up: tells the *proposed* owner that they were nominated,
    and that the current owner still has to confirm. Without this they only
    ever found out by noticing their role had changed."""
    return _send_templated(
        LifecycleEmailTemplate.Trigger.OWNER_TRANSFER_PROPOSED,
        _transfer_context(current_owner_email, new_owner_email, tenant_slug),
        [new_owner_email],
        _OWNER_PROPOSED_FALLBACK_SUBJECT,
        _OWNER_PROPOSED_FALLBACK_BODY,
    )


def send_owner_transfer_confirmed_email(
    previous_owner_email: str, new_owner_email: str, tenant_slug: str, recipients: list[str]
) -> bool:
    """PG-182 follow-up: confirms a completed transfer. Sent to everyone
    involved -- the new owner needs to know they now hold the publication, and
    the previous owner needs a record that their role changed to billing admin."""
    return _send_templated(
        LifecycleEmailTemplate.Trigger.OWNER_TRANSFER_CONFIRMED,
        _transfer_context(previous_owner_email, new_owner_email, tenant_slug),
        recipients,
        _OWNER_CONFIRMED_FALLBACK_SUBJECT,
        _OWNER_CONFIRMED_FALLBACK_BODY,
    )


def send_owner_transfer_rejected_email(
    current_owner_email: str, new_owner_email: str, tenant_slug: str, recipients: list[str]
) -> bool:
    """PG-182 follow-up: tells the other parties that a pending transfer was
    rejected or cancelled, so a proposed owner isn't left waiting on an email
    that will never come. One template covers both outcomes -- from the
    recipient's side the result is identical (nothing changed)."""
    return _send_templated(
        LifecycleEmailTemplate.Trigger.OWNER_TRANSFER_REJECTED,
        _transfer_context(current_owner_email, new_owner_email, tenant_slug),
        recipients,
        _OWNER_REJECTED_FALLBACK_SUBJECT,
        _OWNER_REJECTED_FALLBACK_BODY,
    )


def send_ghost_delivery_alert(owner_email: str, tenant_slug: str) -> bool:
    """PG-192: warns a creator when access delivery to their Ghost site has
    been failing repeatedly (e.g. a rotated/expired Ghost Admin API key, or
    Ghost being unreachable) -- new purchases silently stop unlocking until
    they fix it.

    The copy is admin-editable via the GHOST_DELIVERY_FAILING
    LifecycleEmailTemplate (edited alongside the subscription templates in
    Django Admin). Placeholders: $email, $tenant, $url. Disabling that template
    intentionally silences the alert; if the row is missing
    entirely we fall back to the built-in copy so the alert never goes dark by
    accident. Best-effort and fail-safe: a send failure is logged, never
    raised. The command dedups (only calls this on the healthy -> failing
    transition). Returns True only if the send succeeded."""
    return _send_templated(
        LifecycleEmailTemplate.Trigger.GHOST_DELIVERY_FAILING,
        {
            "email": owner_email,
            "tenant": tenant_slug,
            "url": app_url(f"/t/{tenant_slug}/connection/ghost"),
        },
        [owner_email],
        _GHOST_ALERT_FALLBACK_SUBJECT,
        _GHOST_ALERT_FALLBACK_BODY,
    )


_MEMBER_REMOVED_FALLBACK_SUBJECT = "You were removed from $tenant on PayGlue"
_MEMBER_REMOVED_FALLBACK_BODY = (
    "Hi,\n\n"
    "$actor removed your access to the publication \"$tenant\" on PayGlue.\n\n"
    "You can no longer see its connections, paywalls or events. Any other "
    "publications you belong to are unaffected.\n\n"
    "If you did not expect this, contact whoever runs that publication. We "
    "cannot restore access on their behalf.\n\n"
    f"{_SIGN_OFF}"
)

_MEMBER_REMOVED_NOTICE_FALLBACK_SUBJECT = "$member was removed from $tenant"
_MEMBER_REMOVED_NOTICE_FALLBACK_BODY = (
    "Hi,\n\n"
    "$actor removed $member ($role) from the publication \"$tenant\" on PayGlue.\n\n"
    "You are getting this because you are responsible for that publication. "
    "If this was not expected, review your team now:\n\n"
    "$url\n\n"
    f"{_SIGN_OFF}"
)


def send_team_member_removed_emails(
    removed_email: str,
    removed_role: str,
    actor_email: str,
    tenant_slug: str,
    notice_recipients: list[str],
) -> bool:
    """Tells everyone who matters that somebody lost access to a publication.

    Until this existed, removal was silent: the person simply stopped being
    able to see the publication, with nothing saying why or by whom, and
    nobody responsible for the publication was told either. Access changes
    that leave no trace are how quiet takeovers work, which is the whole
    reason the ownership transfer already emails every party.

    Two separate templates on purpose. The removed person is reading about
    something that happened *to* them; the owners are reading a receipt about
    somebody else. One shared wording would be wrong for one of them.

    Fail-safe like the rest of `_send_templated`: a failed send is logged, not
    raised, so a mail outage cannot block a removal the caller already
    committed. Returns True only if every send succeeded.
    """
    context = {
        "member": removed_email,
        "role": removed_role,
        "actor": actor_email,
        "tenant": tenant_slug,
        "url": app_url(f"/t/{tenant_slug}/team"),
    }
    to_removed = _send_templated(
        LifecycleEmailTemplate.Trigger.TEAM_MEMBER_REMOVED,
        context,
        [removed_email],
        _MEMBER_REMOVED_FALLBACK_SUBJECT,
        _MEMBER_REMOVED_FALLBACK_BODY,
    )
    # The removed person must never also receive the owners' receipt, which
    # would tell them who else was informed.
    recipients = [r for r in notice_recipients if r and r != removed_email]
    to_notice = (
        _send_templated(
            LifecycleEmailTemplate.Trigger.TEAM_MEMBER_REMOVED_NOTICE,
            context,
            recipients,
            _MEMBER_REMOVED_NOTICE_FALLBACK_SUBJECT,
            _MEMBER_REMOVED_NOTICE_FALLBACK_BODY,
        )
        if recipients
        else True
    )
    return to_removed and to_notice


_ACCOUNT_DELETED_FALLBACK_SUBJECT = "Your PayGlue account has been deleted"
_ACCOUNT_DELETED_FALLBACK_BODY = (
    "Hi,\n\n"
    "Your PayGlue account has been deleted. This is your confirmation.\n\n"
    "It has already happened, not scheduled: your profile, the publications "
    "you solely owned, their connections, paywalls, buy buttons, pricing "
    "tables, product mappings, stored provider credentials and webhook history "
    "were removed when you confirmed, along with your sign-in account.\n\n"
    "Two things are worth knowing:\n\n"
    "Your Ghost site is untouched. Member access lives in your own Ghost "
    "instance, not in PayGlue, so nobody loses access because you closed this "
    "account.\n\n"
    "Invoices and payment records are not ours to delete. They sit with our "
    "payment provider, who is the merchant of record for your purchase and is "
    "required to keep them for the statutory period. GDPR Article 17(3)(b) "
    "covers exactly this. We hold no copy and cannot remove theirs.\n\n"
    "Encrypted backups are kept on a 7-day rolling window, so a copy of your "
    "data can survive there for up to seven days before it ages out. Nothing "
    "reads from those backups except disaster recovery.\n\n"
    "If you did not do this, reply immediately.\n\n"
    f"{_SIGN_OFF}"
)


def send_account_deleted_email(email: str) -> bool:
    """Confirms a completed self-service deletion.

    Deliberately worded in the past tense. The deletion is synchronous: by the
    time this sends, the rows are gone. A "within 24 hours" or "within 30 days"
    phrasing would understate what actually happened and invent a deadline none
    of our documents carry -- the DPA's 30 days is an outer bound on the same
    promise, not a queue this sits in.

    Fail-safe like every other lifecycle mail: a send failure is logged, never
    raised. The account is already gone at this point, so throwing here would
    turn a successful deletion into a 500 for something that did succeed.
    """
    return _send_templated(
        LifecycleEmailTemplate.Trigger.ACCOUNT_DELETED,
        {"email": email},
        [email],
        _ACCOUNT_DELETED_FALLBACK_SUBJECT,
        _ACCOUNT_DELETED_FALLBACK_BODY,
    )

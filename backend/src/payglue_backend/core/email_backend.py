# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-202: send transactional mail through Resend's HTTPS API instead of SMTP.

Found live: Django's SMTP backend never got a connection to smtp.resend.com:465
from Railway -- socket.connect() just blocked until gunicorn's worker timeout
killed the worker mid-request (traceback ended in handle_abort/SystemExit). Like
most cloud hosts, Railway blocks outbound SMTP ports (25/465/587) as anti-spam,
so no lifecycle email ever left the box and nothing showed up in Resend at all.

Resend's REST API is plain HTTPS on 443, which is never blocked, so this backend
posts the message there instead. urllib only -- no new dependency, same style as
the Creem/Supabase clients.

PG-208: EMAIL_REDIRECT_TO turns this into a safe backend for staging. With it
set, every recipient is replaced by that one address before the request leaves.
The alternative for staging was Django's console backend, which proves nothing:
it never shows that the domain is verified, that the branded HTML renders in a
real client, or that Resend accepts the payload at all. This exercises the real
path while making it impossible to write to anybody but ourselves.
"""
import json
from urllib import error, request

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

RESEND_API_URL = "https://api.resend.com/emails"


class ResendAPIEmailBackend(BaseEmailBackend):
    """Django email backend posting to Resend's HTTPS API.

    Honors fail_silently like any backend: send_mail() callers that already
    try/except (all the lifecycle senders do) still get a raised exception with
    the real Resend error, so the admin "send test" button can show it.
    """

    def send_messages(self, email_messages) -> int:
        if not email_messages:
            return 0

        api_key = getattr(settings, "RESEND_API_KEY", "")
        if not api_key:
            if not self.fail_silently:
                raise RuntimeError(
                    "RESEND_API_KEY is not set -- cannot send mail via the Resend API."
                )
            return 0

        sent = 0
        for message in email_messages:
            try:
                self._send(message, api_key)
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return sent

    def _send(self, message, api_key: str) -> None:
        redirect_to = getattr(settings, "EMAIL_REDIRECT_TO", "")

        payload = {
            "from": message.from_email or settings.DEFAULT_FROM_EMAIL,
            "to": list(message.to),
            "subject": message.subject,
            "text": message.body,
        }
        if message.cc:
            payload["cc"] = list(message.cc)
        if message.bcc:
            payload["bcc"] = list(message.bcc)
        if message.reply_to:
            payload["reply_to"] = list(message.reply_to)

        if redirect_to:
            # Everything, including cc and bcc, or a staging cron would still
            # reach a real person through a copy line. The original recipients
            # go into the subject and a header so a redirected mail is never
            # mistaken for a real one, and so it stays obvious who it was for.
            original = ", ".join(
                list(message.to) + list(message.cc or []) + list(message.bcc or [])
            )
            payload["to"] = [redirect_to]
            payload.pop("cc", None)
            payload.pop("bcc", None)
            payload["subject"] = f"[staging -> {original}] {payload['subject']}"
            payload["headers"] = {"X-PayGlue-Original-To": original or "(none)"}
        # EmailMultiAlternatives carries the branded HTML part here.
        for content, mimetype in getattr(message, "alternatives", []) or []:
            if mimetype == "text/html":
                payload["html"] = content
                break

        req = request.Request(
            url=RESEND_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "PayGlue/1.0 (https://payglue.io)",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as resp:
                resp.read()
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8") if exc.fp else ""
            # Surface Resend's own message (unverified domain, bad key, ...) --
            # that's exactly what the admin test button shows André.
            raise RuntimeError(f"Resend API {exc.code}: {body}") from exc

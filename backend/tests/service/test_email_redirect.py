# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-208: the staging safety net on outgoing mail.

Staging runs the same nightly cron as production, over seeded accounts with
invented addresses. Sending to those for real would bounce, and the bounces
land on payglue.io's sending reputation -- damage that shows up later as real
customer mail going to spam, with no obvious cause.

So these tests are less about a feature and more about a guarantee: with
EMAIL_REDIRECT_TO set, no address other than that one can leave the process.
"""
import json
from unittest import mock

import pytest
from django.core.mail import EmailMultiAlternatives

from payglue_backend.core.email_backend import ResendAPIEmailBackend


def _capture(monkeypatch):
    """Grab the payload the backend would POST, without any network."""
    sent = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"{}"

    def _urlopen(req, timeout=None):
        sent["payload"] = json.loads(req.data.decode())
        return _Response()

    monkeypatch.setattr("payglue_backend.core.email_backend.request.urlopen", _urlopen)
    return sent


@pytest.fixture
def mail_message():
    message = EmailMultiAlternatives(
        subject="Your invoice",
        body="plain text",
        from_email="PayGlue <ops@example.com>",
        to=["reader@example.com"],
        cc=["cc@example.com"],
        bcc=["bcc@example.com"],
    )
    message.attach_alternative("<p>html</p>", "text/html")
    return message


# --- the guarantee --------------------------------------------------------


def test_every_recipient_is_replaced(settings, monkeypatch, mail_message) -> None:
    settings.RESEND_API_KEY = "key"
    settings.EMAIL_REDIRECT_TO = "andre@nafdo.de"
    sent = _capture(monkeypatch)

    ResendAPIEmailBackend().send_messages([mail_message])

    assert sent["payload"]["to"] == ["andre@nafdo.de"]


def test_cc_and_bcc_are_dropped_entirely(settings, monkeypatch, mail_message) -> None:
    """Redirecting only `to` would still deliver to a real person through a
    copy line, which is the whole failure this exists to prevent."""
    settings.RESEND_API_KEY = "key"
    settings.EMAIL_REDIRECT_TO = "andre@nafdo.de"
    sent = _capture(monkeypatch)

    ResendAPIEmailBackend().send_messages([mail_message])

    assert "cc" not in sent["payload"]
    assert "bcc" not in sent["payload"]


def test_no_original_address_survives_anywhere_it_could_be_delivered_to(
    settings, monkeypatch, mail_message
) -> None:
    settings.RESEND_API_KEY = "key"
    settings.EMAIL_REDIRECT_TO = "andre@nafdo.de"
    sent = _capture(monkeypatch)

    ResendAPIEmailBackend().send_messages([mail_message])

    deliverable = [sent["payload"]["to"], sent["payload"].get("cc", []), sent["payload"].get("bcc", [])]
    flat = [addr for group in deliverable for addr in group]
    assert flat == ["andre@nafdo.de"]


# --- staying recognisable -------------------------------------------------


def test_the_subject_says_who_it_was_for(settings, monkeypatch, mail_message) -> None:
    """A redirected mail must never be mistaken for a real one, and it is
    useless if you cannot tell which account triggered it."""
    settings.RESEND_API_KEY = "key"
    settings.EMAIL_REDIRECT_TO = "andre@nafdo.de"
    sent = _capture(monkeypatch)

    ResendAPIEmailBackend().send_messages([mail_message])

    subject = sent["payload"]["subject"]
    assert subject.startswith("[staging -> ")
    assert "reader@example.com" in subject
    assert "Your invoice" in subject


def test_the_original_recipients_are_kept_in_a_header(
    settings, monkeypatch, mail_message
) -> None:
    settings.RESEND_API_KEY = "key"
    settings.EMAIL_REDIRECT_TO = "andre@nafdo.de"
    sent = _capture(monkeypatch)

    ResendAPIEmailBackend().send_messages([mail_message])

    header = sent["payload"]["headers"]["X-PayGlue-Original-To"]
    for addr in ("reader@example.com", "cc@example.com", "bcc@example.com"):
        assert addr in header


# --- production must be untouched ----------------------------------------


def test_without_the_setting_nothing_changes(settings, monkeypatch, mail_message) -> None:
    """The setting is empty in production. Every assertion here is the old
    behaviour, so this test fails if the redirect ever leaks into it."""
    settings.RESEND_API_KEY = "key"
    settings.EMAIL_REDIRECT_TO = ""
    sent = _capture(monkeypatch)

    ResendAPIEmailBackend().send_messages([mail_message])

    payload = sent["payload"]
    assert payload["to"] == ["reader@example.com"]
    assert payload["cc"] == ["cc@example.com"]
    assert payload["bcc"] == ["bcc@example.com"]
    assert payload["subject"] == "Your invoice"
    assert "headers" not in payload


def test_the_html_part_still_goes_out(settings, monkeypatch, mail_message) -> None:
    """Proving the branded template renders in a real client is half the
    reason staging uses Resend rather than the console backend."""
    settings.RESEND_API_KEY = "key"
    settings.EMAIL_REDIRECT_TO = "andre@nafdo.de"
    sent = _capture(monkeypatch)

    ResendAPIEmailBackend().send_messages([mail_message])

    assert sent["payload"]["html"] == "<p>html</p>"
    assert sent["payload"]["text"] == "plain text"

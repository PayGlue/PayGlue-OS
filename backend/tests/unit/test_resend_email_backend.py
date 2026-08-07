# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-202: Railway blocks outbound SMTP, so mail goes through Resend's HTTPS
API instead. These lock in the payload shape and that Resend's own error text
reaches the caller (the admin test button shows it)."""
import io
import json

import pytest

from payglue_backend.core import email_backend as eb
from payglue_backend.core.email_backend import ResendAPIEmailBackend


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def read(self):
        return b"{}"


def _message():
    from django.core.mail import EmailMultiAlternatives

    msg = EmailMultiAlternatives(
        "Subj", "plain body", "PayGlue <noreply@example.com>", ["a@example.com"]
    )
    msg.attach_alternative("<b>branded</b>", "text/html")
    return msg


def test_posts_expected_payload_including_html_part(settings, monkeypatch) -> None:
    settings.RESEND_API_KEY = "re_test"
    captured: dict = {}

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr(eb.request, "urlopen", _fake_urlopen)

    assert ResendAPIEmailBackend().send_messages([_message()]) == 1
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer re_test"
    payload = captured["payload"]
    assert payload["from"] == "PayGlue <noreply@example.com>"
    assert payload["to"] == ["a@example.com"]
    assert payload["subject"] == "Subj"
    assert payload["text"] == "plain body"
    assert payload["html"] == "<b>branded</b>"


def test_resend_error_text_reaches_the_caller(settings, monkeypatch) -> None:
    settings.RESEND_API_KEY = "re_test"

    def _raise(req, timeout=None):
        raise eb.error.HTTPError(
            url="https://api.resend.com/emails",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"The example.com domain is not verified"}'),
        )

    monkeypatch.setattr(eb.request, "urlopen", _raise)

    with pytest.raises(RuntimeError) as excinfo:
        ResendAPIEmailBackend(fail_silently=False).send_messages([_message()])
    assert "not verified" in str(excinfo.value)
    assert "403" in str(excinfo.value)


def test_missing_api_key_raises_instead_of_silently_dropping(settings) -> None:
    settings.RESEND_API_KEY = ""

    with pytest.raises(RuntimeError):
        ResendAPIEmailBackend(fail_silently=False).send_messages([_message()])

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-202: the owner-transfer and ghost-delivery emails must be English (they
were seeded in German) and sent with the branded HTML part attached."""
import pytest
from django.core import mail

from payglue_backend.authn.lifecycle_emails import (
    send_ghost_delivery_alert,
    send_owner_transfer_request_email,
)

pytestmark = pytest.mark.django_db


def _html_part(msg) -> str:
    parts = [content for content, mimetype in msg.alternatives if mimetype == "text/html"]
    assert parts, "expected a text/html alternative"
    return parts[0]


def test_owner_transfer_email_is_english_and_branded() -> None:
    assert send_owner_transfer_request_email("owner@example.com", "new@example.com", "pub") is True

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "Ownership transfer requested" in msg.subject
    assert "Owner-Wechsel" not in (msg.subject + msg.body)
    html = _html_part(msg)
    assert "background-color:#0f172a" in html  # branded shell
    assert "transfer ownership" in html


def test_ghost_delivery_alert_is_english_and_branded() -> None:
    assert send_ghost_delivery_alert("owner@example.com", "pub") is True

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "Ghost connection is failing" in msg.subject
    assert "schlaegt gerade fehl" not in (msg.subject + msg.body)
    html = _html_part(msg)
    assert "background-color:#0f172a" in html

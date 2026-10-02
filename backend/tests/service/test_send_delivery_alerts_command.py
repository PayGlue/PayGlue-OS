# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The nightly send_delivery_alerts (PG-319, PG-326). It retries creator alerts
the worker could not send, escalates a still-failing incident internally once
after 48h, and clears an incident the worker missed when a later event went
through."""

from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile
from payglue_backend.webhooks.models import DeliveryAlert, WebhookInboundEvent


@pytest.fixture(autouse=True)
def _addresses(settings):
    settings.PUBLIC_APP_BASE_URL = "https://dashboard.example.com"
    settings.INTERNAL_ADMIN_EMAIL = "team@example.com"


pytestmark = pytest.mark.django_db

_S = WebhookInboundEvent.Status


def _tenant_with_owner(slug: str, email: str) -> Tenant:
    tenant = Tenant.objects.create(slug=slug, schema_name=slug.replace("-", "_"))
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    TenantMembership.objects.create(
        tenant=tenant, user_profile=owner, role=TenantMembership.Role.OWNER
    )
    return tenant


def _event(slug: str, status: str, *, hours_ago: float) -> None:
    event = WebhookInboundEvent.objects.create(
        tenant_slug=slug,
        provider="creem",
        status=status,
        payload_raw=b"",
        endpoint_path="/webhooks/creem",
    )
    WebhookInboundEvent.objects.filter(pk=event.pk).update(
        created_at=timezone.now() - timedelta(hours=hours_ago)
    )


def _failing(slug: str, *, hours_ago: float, **extra) -> DeliveryAlert:
    moment = timezone.now() - timedelta(hours=hours_ago)
    return DeliveryAlert.objects.create(
        tenant_slug=slug,
        **{
            "state": "failing",
            "kind": "provider",
            "provider": "creem",
            "failure_count": 4,
            "failing_since": "25 Aug 2026",
            "first_failed_at": moment,
            "notified_at": moment,
            **extra,
        },
    )


def _pending(slug: str, *, hours_ago: float, reason: str) -> DeliveryAlert:
    return _failing(
        slug,
        hours_ago=hours_ago,
        state="pending",
        notified_at=None,
        send_attempts=1,
        last_send_error=reason,
    )


def test_escalates_internally_once_after_48h_without_a_processed_event() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    alert = _failing("acme", hours_ago=50)
    _event("acme", _S.FAILED, hours_ago=50)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 1
    notice = mail.outbox[0]
    assert notice.to == ["team@example.com"]
    assert "acme" in notice.subject
    assert "was told on" in notice.body
    assert "owner@example.com" in notice.body
    assert "Creem" in notice.body
    alert.refresh_from_db()
    assert alert.escalated_at is not None

    call_command("send_delivery_alerts")
    assert len(mail.outbox) == 1, "the second night must not send a second notice"


def test_no_escalation_before_48h() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    _failing("acme", hours_ago=20)
    _event("acme", _S.FAILED, hours_ago=20)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0


def test_processed_event_after_the_alert_resets_instead_of_escalating() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    alert = _failing("acme", hours_ago=60)
    _event("acme", _S.FAILED, hours_ago=60)
    _event("acme", _S.PROCESSED, hours_ago=2)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0
    alert.refresh_from_db()
    assert alert.state == "healthy"


def test_healthy_tenant_with_failures_is_left_to_the_worker() -> None:
    """The creator alert is the worker's job; the nightly run must not revive
    the old three-in-24h rule for a tenant nobody recorded an incident for."""
    _tenant_with_owner("acme", "owner@example.com")
    for h in (3, 2, 1):
        _event("acme", _S.FAILED, hours_ago=h)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0
    assert not DeliveryAlert.objects.exists()


def test_a_pending_alert_is_sent_by_the_nightly_run() -> None:
    """PG-326: the worker could not mail. The cron can, so the creator hears
    about it the same night instead of never."""
    _tenant_with_owner("acme", "owner@example.com")
    alert = _pending(
        "acme", hours_ago=5, reason="RuntimeError: RESEND_API_KEY is not set"
    )
    _event("acme", _S.DEAD_LETTER, hours_ago=5)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["owner@example.com"]
    assert "Creem" in mail.outbox[0].subject
    alert.refresh_from_db()
    assert alert.state == "failing"
    assert alert.notified_at is not None
    assert alert.last_send_error == ""
    assert alert.send_attempts == 2

    call_command("send_delivery_alerts")
    assert len(mail.outbox) == 1, "told once, not every night"


def test_a_pending_alert_that_recovered_is_cleared_without_a_mail() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    alert = _pending("acme", hours_ago=30, reason="whatever")
    _event("acme", _S.DEAD_LETTER, hours_ago=30)
    _event("acme", _S.PROCESSED, hours_ago=1)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0
    alert.refresh_from_db()
    assert alert.state == "healthy"


def test_a_creator_who_cannot_be_told_still_reaches_the_operator_after_48h() -> None:
    """No owner address: the retry keeps failing. The operator must hear about
    it anyway, and must read that the creator does not know."""
    Tenant.objects.create(slug="lonely", schema_name="lonely")
    alert = _pending("lonely", hours_ago=50, reason="stale")
    _event("lonely", _S.DEAD_LETTER, hours_ago=50)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 1
    notice = mail.outbox[0]
    assert notice.to == ["team@example.com"]
    assert "has NOT been told" in notice.body
    assert "no owner" in notice.body
    alert.refresh_from_db()
    assert alert.state == "pending"
    assert alert.escalated_at is not None


def test_dry_run_sends_nothing_and_writes_no_state() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    failing = _failing("acme", hours_ago=50)
    _tenant_with_owner("beta", "beta@example.com")
    pending = _pending("beta", hours_ago=5, reason="x")
    _event("acme", _S.FAILED, hours_ago=50)
    _event("beta", _S.FAILED, hours_ago=5)

    call_command("send_delivery_alerts", "--dry-run")

    assert len(mail.outbox) == 0
    failing.refresh_from_db()
    pending.refresh_from_db()
    assert failing.escalated_at is None
    assert pending.state == "pending"
    assert pending.send_attempts == 1


def test_silent_without_internal_address(settings) -> None:
    settings.INTERNAL_ADMIN_EMAIL = ""
    _tenant_with_owner("acme", "owner@example.com")
    alert = _failing("acme", hours_ago=50)
    _event("acme", _S.FAILED, hours_ago=50)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0
    alert.refresh_from_db()
    assert alert.escalated_at is None

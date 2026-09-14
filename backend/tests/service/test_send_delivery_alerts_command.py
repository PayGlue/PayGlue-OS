# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-319: the nightly send_delivery_alerts no longer mails creators. It
escalates a still-failing incident internally once, 48h after the creator was
told, and clears an incident the worker missed when a later event went through."""

from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile
from payglue_backend.webhooks.models import IntegrationConfig, WebhookInboundEvent


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


def _ghost_config(
    slug: str, *, enabled: bool = True, metadata: dict | None = None
) -> IntegrationConfig:
    return IntegrationConfig.objects.create(
        tenant_slug=slug,
        provider_key="cms",
        enabled=enabled,
        provider_type="ghost",
        metadata=metadata or {},
    )


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


def _failing(hours_ago: float, **extra) -> dict:
    return {
        "delivery_alert": {
            "state": "failing",
            "kind": "provider",
            "provider": "creem",
            "count": 4,
            "since": "25 Aug 2026",
            "notified_at": (timezone.now() - timedelta(hours=hours_ago)).isoformat(),
            "escalated_at": None,
            **extra,
        }
    }


def test_escalates_internally_once_after_48h_without_a_processed_event() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    config = _ghost_config("acme", metadata=_failing(hours_ago=50))
    _event("acme", _S.FAILED, hours_ago=50)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 1
    notice = mail.outbox[0]
    assert notice.to == ["team@example.com"]
    assert "acme" in notice.subject
    assert "owner@example.com" in notice.body
    assert "Creem" in notice.body
    config.refresh_from_db()
    assert config.metadata["delivery_alert"]["escalated_at"]

    call_command("send_delivery_alerts")
    assert len(mail.outbox) == 1, "the second night must not send a second notice"


def test_no_escalation_before_48h() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    _ghost_config("acme", metadata=_failing(hours_ago=20))
    _event("acme", _S.FAILED, hours_ago=20)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0


def test_processed_event_after_the_alert_resets_instead_of_escalating() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    config = _ghost_config("acme", metadata=_failing(hours_ago=60))
    _event("acme", _S.FAILED, hours_ago=60)
    _event("acme", _S.PROCESSED, hours_ago=2)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0
    config.refresh_from_db()
    assert config.metadata["delivery_alert"] == {"state": "healthy"}


def test_healthy_tenant_with_failures_is_left_to_the_worker() -> None:
    """The creator alert is the worker's job now; the nightly run must not
    revive the old three-in-24h rule."""
    _tenant_with_owner("acme", "owner@example.com")
    config = _ghost_config("acme")
    for h in (3, 2, 1):
        _event("acme", _S.FAILED, hours_ago=h)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0
    config.refresh_from_db()
    assert "delivery_alert" not in config.metadata


def test_state_from_the_old_command_gets_a_clock_and_escalates_two_days_later() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    config = _ghost_config("acme", metadata={"delivery_alert": {"state": "failing"}})
    _event("acme", _S.FAILED, hours_ago=100)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0
    config.refresh_from_db()
    assert config.metadata["delivery_alert"]["notified_at"]


def test_dry_run_sends_nothing_and_writes_no_state() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    before = _failing(hours_ago=50)
    config = _ghost_config("acme", metadata=before)
    _event("acme", _S.FAILED, hours_ago=50)

    call_command("send_delivery_alerts", "--dry-run")

    assert len(mail.outbox) == 0
    config.refresh_from_db()
    assert config.metadata == before


def test_silent_without_internal_address(settings) -> None:
    settings.INTERNAL_ADMIN_EMAIL = ""
    _tenant_with_owner("acme", "owner@example.com")
    config = _ghost_config("acme", metadata=_failing(hours_ago=50))
    _event("acme", _S.FAILED, hours_ago=50)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0
    config.refresh_from_db()
    assert not config.metadata["delivery_alert"]["escalated_at"], (
        "an unsent notice must not count as sent"
    )


def test_ignores_tenant_without_enabled_ghost() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    _ghost_config("acme", enabled=False, metadata=_failing(hours_ago=50))
    _event("acme", _S.FAILED, hours_ago=50)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0

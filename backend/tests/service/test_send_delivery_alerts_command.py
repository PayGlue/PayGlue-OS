# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-192: send_delivery_alerts emails a tenant owner when access delivery to
their Ghost site is repeatedly failing (last 3 terminal outcomes within 24h
all failed/dead_letter), dedup'd to the healthy -> failing transition."""
from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.tenants.models import (
    LifecycleEmailTemplate,
    Tenant,
    TenantMembership,
    UserProfile,
)
from payglue_backend.webhooks.models import IntegrationConfig, WebhookInboundEvent

# Dashboard links in emails come from PUBLIC_APP_BASE_URL since PG-238. Without
# it app_url() returns empty, which is the correct behaviour for an install
# that has not been told where its dashboard lives.
@pytest.fixture(autouse=True)
def _dashboard_address(settings):
    settings.PUBLIC_APP_BASE_URL = "https://dashboard.example.com"



pytestmark = pytest.mark.django_db

_S = WebhookInboundEvent.Status


def _tenant_with_owner(slug: str, email: str) -> Tenant:
    tenant = Tenant.objects.create(slug=slug, schema_name=slug.replace("-", "_"))
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    TenantMembership.objects.create(
        tenant=tenant, user_profile=owner, role=TenantMembership.Role.OWNER
    )
    return tenant


def _ghost_config(slug: str, *, enabled: bool = True, metadata: dict | None = None) -> IntegrationConfig:
    return IntegrationConfig.objects.create(
        tenant_slug=slug,
        provider_key="cms",
        enabled=enabled,
        provider_type="ghost",
        metadata=metadata or {},
    )


def _event(slug: str, status: str, *, minutes_ago: int) -> None:
    """Create a webhook event and stamp created_at (auto_now_add ignores the
    passed value, so we set it explicitly for deterministic ordering)."""
    event = WebhookInboundEvent.objects.create(
        tenant_slug=slug,
        provider="polar",
        status=status,
        payload_raw=b"",
        endpoint_path="/webhooks/polar",
    )
    WebhookInboundEvent.objects.filter(pk=event.pk).update(
        created_at=timezone.now() - timedelta(minutes=minutes_ago)
    )


def test_alerts_owner_on_three_consecutive_failures() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    config = _ghost_config("acme")
    _event("acme", _S.FAILED, minutes_ago=30)
    _event("acme", _S.DEAD_LETTER, minutes_ago=20)
    _event("acme", _S.FAILED, minutes_ago=10)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["owner@example.com"]
    config.refresh_from_db()
    assert config.metadata["delivery_alert"]["state"] == "failing"


def test_does_not_realert_while_still_failing() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    _ghost_config("acme", metadata={"delivery_alert": {"state": "failing"}})
    _event("acme", _S.FAILED, minutes_ago=30)
    _event("acme", _S.FAILED, minutes_ago=20)
    _event("acme", _S.FAILED, minutes_ago=10)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0


def test_recovery_resets_state_without_email() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    config = _ghost_config("acme", metadata={"delivery_alert": {"state": "failing"}})
    # Newest terminal outcome is a success -> not failing anymore.
    _event("acme", _S.FAILED, minutes_ago=30)
    _event("acme", _S.FAILED, minutes_ago=20)
    _event("acme", _S.PROCESSED, minutes_ago=5)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0
    config.refresh_from_db()
    assert config.metadata["delivery_alert"]["state"] == "healthy"


def test_no_alert_with_a_recent_success_in_the_streak() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    _ghost_config("acme")
    _event("acme", _S.FAILED, minutes_ago=30)
    _event("acme", _S.PROCESSED, minutes_ago=20)
    _event("acme", _S.FAILED, minutes_ago=10)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0


def test_no_alert_with_fewer_than_three_terminal_events() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    _ghost_config("acme")
    _event("acme", _S.FAILED, minutes_ago=20)
    _event("acme", _S.FAILED, minutes_ago=10)
    # A skipped/in-flight event is not terminal and must not count toward the streak.
    _event("acme", _S.SKIPPED, minutes_ago=5)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0


def test_dry_run_sends_nothing_and_writes_no_state() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    config = _ghost_config("acme")
    _event("acme", _S.FAILED, minutes_ago=30)
    _event("acme", _S.FAILED, minutes_ago=20)
    _event("acme", _S.FAILED, minutes_ago=10)

    call_command("send_delivery_alerts", "--dry-run")

    assert len(mail.outbox) == 0
    config.refresh_from_db()
    assert "delivery_alert" not in config.metadata


def test_admin_edited_template_copy_is_used() -> None:
    # The ghost_delivery_failing template is seeded (enabled) by migration;
    # editing it in the admin must change the sent email.
    _tenant_with_owner("acme", "owner@example.com")
    _ghost_config("acme")
    LifecycleEmailTemplate.objects.filter(trigger="ghost_delivery_failing").update(
        subject="Ghost kaputt bei $tenant", body="Check $url"
    )
    _event("acme", _S.FAILED, minutes_ago=30)
    _event("acme", _S.FAILED, minutes_ago=20)
    _event("acme", _S.FAILED, minutes_ago=10)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Ghost kaputt bei acme"
    assert "https://dashboard.example.com/t/acme/connection/ghost" in mail.outbox[0].body


def test_disabled_template_silences_the_alert() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    _ghost_config("acme")
    LifecycleEmailTemplate.objects.filter(trigger="ghost_delivery_failing").update(enabled=False)
    _event("acme", _S.FAILED, minutes_ago=30)
    _event("acme", _S.FAILED, minutes_ago=20)
    _event("acme", _S.FAILED, minutes_ago=10)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0


def test_ignores_tenant_without_enabled_ghost() -> None:
    _tenant_with_owner("acme", "owner@example.com")
    _ghost_config("acme", enabled=False)
    _event("acme", _S.FAILED, minutes_ago=30)
    _event("acme", _S.FAILED, minutes_ago=20)
    _event("acme", _S.FAILED, minutes_ago=10)

    call_command("send_delivery_alerts")

    assert len(mail.outbox) == 0

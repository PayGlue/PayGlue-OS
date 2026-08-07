# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-194 (GDPR): purge_expired_logs deletes webhook event + audit log rows
older than LOG_RETENTION_DAYS, keeps recent ones, and is a no-op under
--dry-run."""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.tenants.models import PublicAuditEvent, Tenant, TenantMembership, UserProfile
from payglue_backend.webhooks.models import WebhookEventRecord, WebhookInboundEvent


pytestmark = pytest.mark.django_db


def _old(dt_field_days_ago: int):
    return timezone.now() - timedelta(days=dt_field_days_ago)


def _make_webhook_event(tenant_slug: str, created_days_ago: int) -> WebhookInboundEvent:
    ev = WebhookInboundEvent.objects.create(
        tenant_slug=tenant_slug,
        provider="creem",
        status=WebhookInboundEvent.Status.PROCESSED,
        payload_raw=b'{"email":"customer@example.com"}',
        endpoint_path="/webhooks/creem",
    )
    # created_at is auto_now_add -- override it directly for the test.
    WebhookInboundEvent.objects.filter(pk=ev.pk).update(created_at=_old(created_days_ago))
    return ev


def _make_audit_event(tenant: Tenant, membership, created_days_ago: int) -> PublicAuditEvent:
    ev = PublicAuditEvent.objects.create(
        tenant=tenant,
        actor_membership=membership,
        event_type=PublicAuditEvent.EventType.EVENT_REPLAY_REQUESTED,
        target_type="webhook_event",
        target_id="evt_1",
        metadata={},
    )
    PublicAuditEvent.objects.filter(pk=ev.pk).update(created_at=_old(created_days_ago))
    return ev


def _tenant_with_member(slug: str):
    tenant = Tenant.objects.create(slug=slug, schema_name=slug.replace("-", "_"))
    profile = UserProfile.objects.create(firebase_uid=f"uid-{slug}", email=f"{slug}@example.com")
    membership = TenantMembership.objects.create(
        tenant=tenant, user_profile=profile, role=TenantMembership.Role.OWNER
    )
    return tenant, membership


def test_purges_rows_older_than_retention_window() -> None:
    tenant, membership = _tenant_with_member("purge-old")
    old_wh = _make_webhook_event("purge-old", created_days_ago=120)
    old_audit = _make_audit_event(tenant, membership, created_days_ago=100)

    call_command("purge_expired_logs")

    assert not WebhookInboundEvent.objects.filter(pk=old_wh.pk).exists()
    assert not PublicAuditEvent.objects.filter(pk=old_audit.pk).exists()


def test_keeps_rows_within_retention_window() -> None:
    tenant, membership = _tenant_with_member("keep-recent")
    recent_wh = _make_webhook_event("keep-recent", created_days_ago=10)
    recent_audit = _make_audit_event(tenant, membership, created_days_ago=89)

    call_command("purge_expired_logs")

    assert WebhookInboundEvent.objects.filter(pk=recent_wh.pk).exists()
    assert PublicAuditEvent.objects.filter(pk=recent_audit.pk).exists()


def test_purges_idempotency_records_too() -> None:
    old = WebhookEventRecord.objects.create(
        idempotency_key="idem:old",
        tenant_slug="idem",
        provider="creem",
        provider_event_id="evt_old",
        status=WebhookEventRecord.Status.PROCESSED,
    )
    # WebhookEventRecord ages on started_at (auto_now_add), not created_at.
    WebhookEventRecord.objects.filter(pk=old.pk).update(started_at=_old(200))
    recent = WebhookEventRecord.objects.create(
        idempotency_key="idem:recent",
        tenant_slug="idem",
        provider="creem",
        provider_event_id="evt_recent",
        status=WebhookEventRecord.Status.PROCESSED,
    )

    call_command("purge_expired_logs")

    assert not WebhookEventRecord.objects.filter(pk=old.pk).exists()
    assert WebhookEventRecord.objects.filter(pk=recent.pk).exists()


def test_dry_run_deletes_nothing() -> None:
    tenant, membership = _tenant_with_member("dry")
    old_wh = _make_webhook_event("dry", created_days_ago=120)
    old_audit = _make_audit_event(tenant, membership, created_days_ago=120)

    call_command("purge_expired_logs", "--dry-run")

    assert WebhookInboundEvent.objects.filter(pk=old_wh.pk).exists()
    assert PublicAuditEvent.objects.filter(pk=old_audit.pk).exists()


def test_no_rows_is_a_clean_noop() -> None:
    call_command("purge_expired_logs")


def test_respects_custom_retention_setting(settings) -> None:
    settings.LOG_RETENTION_DAYS = 30
    _make_webhook_event("custom", created_days_ago=45)  # older than 30, within 90

    call_command("purge_expired_logs")

    assert not WebhookInboundEvent.objects.filter(tenant_slug="custom").exists()


def _processed_event(tenant_slug: str, created_days_ago: int, status=None) -> WebhookInboundEvent:
    ev = WebhookInboundEvent.objects.create(
        tenant_slug=tenant_slug,
        provider="creem",
        status=status or WebhookInboundEvent.Status.PROCESSED,
        payload_raw=b'{"email":"customer@example.com"}',
        payload_snapshot={"email": "customer@example.com"},
        endpoint_path="/webhooks/creem",
    )
    WebhookInboundEvent.objects.filter(pk=ev.pk).update(created_at=_old(created_days_ago))
    return ev


def test_scrubs_raw_payload_of_old_processed_events_but_keeps_row_and_snapshot() -> None:
    ev = _processed_event("rp", created_days_ago=10)  # >7d default, <90d

    call_command("purge_expired_logs")

    ev.refresh_from_db()
    # Row and snapshot survive (dashboard still renders); only raw bytes gone.
    assert WebhookInboundEvent.objects.filter(pk=ev.pk).exists()
    assert bytes(ev.payload_raw) == b""
    assert ev.payload_snapshot == {"email": "customer@example.com"}


def test_keeps_raw_payload_within_short_window() -> None:
    ev = _processed_event("rp", created_days_ago=3)  # within 7d

    call_command("purge_expired_logs")

    ev.refresh_from_db()
    assert bytes(ev.payload_raw) != b""


def test_does_not_scrub_raw_payload_of_replayable_statuses() -> None:
    # FAILED / DEAD_LETTER / SKIPPED can still be replayed -> raw body needed.
    failed = _processed_event("rp", created_days_ago=30, status=WebhookInboundEvent.Status.FAILED)
    skipped = _processed_event("rp", created_days_ago=30, status=WebhookInboundEvent.Status.SKIPPED)

    call_command("purge_expired_logs")

    failed.refresh_from_db()
    skipped.refresh_from_db()
    assert bytes(failed.payload_raw) != b""
    assert bytes(skipped.payload_raw) != b""


def test_dry_run_does_not_scrub_raw_payload() -> None:
    ev = _processed_event("rp", created_days_ago=10)

    call_command("purge_expired_logs", "--dry-run")

    ev.refresh_from_db()
    assert bytes(ev.payload_raw) != b""

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from datetime import timedelta
from datetime import datetime
from contextlib import nullcontext

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from payglue_backend.core.errors import (
    AdapterNotRegisteredError,
    CmsApplyEntitlementError,
    InvalidIdempotencyKeyError,
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    MissingCredentialsError,
    MissingCustomerIdentityError,
    UnsupportedEventTypeError,
)
from payglue_backend.core.models import TenantContext
from payglue_backend.tenants.models import Tenant
from payglue_backend.webhooks import wiring
from payglue_backend.webhooks.models import WebhookInboundEvent

if getattr(settings, "DJANGO_TENANTS_ENABLED", False):  # pragma: no cover
    from django_tenants.utils import get_public_schema_name, schema_context


NON_RETRYABLE_EXCEPTIONS = (
    AdapterNotRegisteredError,
    InvalidWebhookSignatureError,
    UnsupportedEventTypeError,
    MissingCustomerIdentityError,
    InvalidIdempotencyKeyError,
    InvalidWebhookPayloadError,
)

RETRYABLE_EXCEPTIONS = (
    CmsApplyEntitlementError,
    MissingCredentialsError,
)


def _is_retryable_error(error: Exception) -> bool:
    """Retry transient upstream/config failures; reject malformed webhook inputs."""
    if isinstance(error, NON_RETRYABLE_EXCEPTIONS):
        return False

    if isinstance(error, RETRYABLE_EXCEPTIONS):
        return True

    return True


def _exponential_backoff_seconds(attempt_number: int) -> int:
    base_seconds = 5
    max_seconds = 300
    return min(base_seconds * (2 ** max(attempt_number - 1, 0)), max_seconds)


def _processing_stale_before(now: datetime) -> datetime:
    timeout_seconds = int(getattr(settings, "WEBHOOK_PROCESSING_TIMEOUT_SECONDS", 900))
    return now - timedelta(seconds=timeout_seconds)


def _update_if_current_processing(
    *,
    event_id: int,
    attempts: int,
    **fields: object,
) -> bool:
    updated = WebhookInboundEvent.objects.filter(
        id=event_id,
        status=WebhookInboundEvent.Status.PROCESSING,
        attempts=attempts,
    ).update(**fields)
    return updated == 1


@shared_task(name="webhooks.process_inbound_webhook_event", ignore_result=True)
def process_inbound_webhook_event(
    event_id: int,
    ignore_timing: bool = False,
    tenant_slug: str | None = None,
    skip_verification: bool = False,
) -> None:
    context_manager = nullcontext()
    if getattr(settings, "DJANGO_TENANTS_ENABLED", False):
        if not tenant_slug:
            raise ValueError("tenant_slug is required when DJANGO_TENANTS_ENABLED=1")
        with schema_context(get_public_schema_name()):
            tenant = Tenant.objects.filter(slug=tenant_slug).only("schema_name").first()
        if tenant is None:
            return
        context_manager = schema_context(tenant.schema_name)

    with context_manager:
        _process_inbound_webhook_event(event_id, ignore_timing=ignore_timing, skip_verification=skip_verification)


def _process_inbound_webhook_event(event_id: int, ignore_timing: bool = False, skip_verification: bool = False) -> None:
    now = timezone.now()
    with transaction.atomic():
        try:
            event = WebhookInboundEvent.objects.select_for_update().get(id=event_id)
        except WebhookInboundEvent.DoesNotExist:
            return

        if event.status in {
            WebhookInboundEvent.Status.PROCESSED,
            WebhookInboundEvent.Status.DEAD_LETTER,
        }:
            return

        if event.status == WebhookInboundEvent.Status.PROCESSING:
            stale_before = _processing_stale_before(now)
            if (
                event.processing_started_at is not None
                and event.processing_started_at > stale_before
            ):
                return

        if not ignore_timing and event.next_attempt_at and event.next_attempt_at > now:
            return

        event.status = WebhookInboundEvent.Status.PROCESSING
        event.attempts += 1
        event.processing_started_at = now
        event.save(
            update_fields=["status", "attempts", "processing_started_at", "updated_at"]
        )

    tenant = Tenant.objects.filter(slug=event.tenant_slug).only("status").first()
    if tenant is None or tenant.status != Tenant.Status.ACTIVE:
        _update_if_current_processing(
            event_id=event.id,
            attempts=event.attempts,
            status=WebhookInboundEvent.Status.FAILED,
            last_error="tenant is not active",
            failed_at=timezone.now(),
            next_attempt_at=None,
            dead_lettered_at=None,
            updated_at=timezone.now(),
        )
        return

    orchestrator = wiring.get_webhook_orchestrator()
    tenant_ctx = TenantContext(tenant_slug=event.tenant_slug)
    try:
        orchestrator.process_webhook(
            payment_provider_key=event.provider,
            cms_provider_key=wiring.get_tenant_cms_provider_key(event.tenant_slug),
            raw_body=bytes(event.payload_raw),
            headers=event.headers_snapshot,
            tenant_ctx=tenant_ctx,
            skip_verification=skip_verification,
        )
    except UnsupportedEventTypeError as exc:
        # Unsupported event types are silently skipped — not a failure, not retried.
        _update_if_current_processing(
            event_id=event.id,
            attempts=event.attempts,
            status=WebhookInboundEvent.Status.SKIPPED,
            last_error=str(exc),
            failed_at=None,
            next_attempt_at=None,
            dead_lettered_at=None,
            updated_at=timezone.now(),
        )
        return
    except Exception as exc:
        error_now = timezone.now()
        retryable = _is_retryable_error(exc)
        last_error = str(exc)
        if retryable and event.attempts < event.max_attempts:
            backoff_seconds = _exponential_backoff_seconds(event.attempts)
            updated = _update_if_current_processing(
                event_id=event.id,
                attempts=event.attempts,
                status=WebhookInboundEvent.Status.FAILED,
                last_error=last_error,
                failed_at=error_now,
                next_attempt_at=error_now + timedelta(seconds=backoff_seconds),
                dead_lettered_at=None,
                updated_at=error_now,
            )
            if not updated:
                return
            if settings.CELERY_TASK_ALWAYS_EAGER:
                process_inbound_webhook_event.delay(
                    event.id,
                    ignore_timing=True,
                    tenant_slug=event.tenant_slug,
                )
            else:
                try:
                    process_inbound_webhook_event.apply_async(
                        kwargs={
                            "event_id": event.id,
                            "ignore_timing": True,
                            "tenant_slug": event.tenant_slug,
                        },
                        countdown=backoff_seconds,
                    )
                except Exception:
                    failure_now = timezone.now()
                    WebhookInboundEvent.objects.filter(
                        id=event.id,
                        status=WebhookInboundEvent.Status.FAILED,
                        attempts=event.attempts,
                    ).update(
                        last_error="queue publish failed",
                        failed_at=failure_now,
                        next_attempt_at=None,
                        status=WebhookInboundEvent.Status.DEAD_LETTER,
                        dead_lettered_at=failure_now,
                        updated_at=failure_now,
                    )
                return

        status = WebhookInboundEvent.Status.FAILED
        dead_lettered_at = None
        if retryable:
            status = WebhookInboundEvent.Status.DEAD_LETTER
            dead_lettered_at = error_now
        _update_if_current_processing(
            event_id=event.id,
            attempts=event.attempts,
            status=status,
            last_error=last_error,
            failed_at=error_now,
            next_attempt_at=None,
            dead_lettered_at=dead_lettered_at,
            updated_at=error_now,
        )
        return

    success_now = timezone.now()
    _update_if_current_processing(
        event_id=event.id,
        attempts=event.attempts,
        status=WebhookInboundEvent.Status.PROCESSED,
        processed_at=success_now,
        next_attempt_at=None,
        last_error="",
        failed_at=None,
        dead_lettered_at=None,
        updated_at=success_now,
    )

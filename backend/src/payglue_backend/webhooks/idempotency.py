# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from payglue_backend.core.errors import InvalidIdempotencyKeyError
from payglue_backend.webhooks.models import WebhookEventRecord


class DbIdempotencyStore:
    def __init__(self, processing_timeout_seconds: int = 600) -> None:
        self._processing_timeout = timedelta(seconds=processing_timeout_seconds)

    def start_processing(self, idempotency_key: str) -> bool:
        tenant_slug, provider, provider_event_id = self._parse_idempotency_key(
            idempotency_key
        )
        stale_before = timezone.now() - self._processing_timeout
        with transaction.atomic():
            record, created = (
                WebhookEventRecord.objects.select_for_update().get_or_create(
                    idempotency_key=idempotency_key,
                    defaults={
                        "tenant_slug": tenant_slug,
                        "provider": provider,
                        "provider_event_id": provider_event_id,
                        "status": WebhookEventRecord.Status.PROCESSING,
                    },
                )
            )
            if created:
                return True

            if record.status == WebhookEventRecord.Status.PROCESSED:
                return False

            if record.status == WebhookEventRecord.Status.RELEASED or (
                record.status == WebhookEventRecord.Status.PROCESSING
                and record.updated_at <= stale_before
            ):
                record.status = WebhookEventRecord.Status.PROCESSING
                record.released_at = None
                record.save(update_fields=["status", "released_at", "updated_at"])
                return True

            return False

    def mark_processed(self, idempotency_key: str) -> None:
        WebhookEventRecord.objects.filter(idempotency_key=idempotency_key).update(
            status=WebhookEventRecord.Status.PROCESSED,
            processed_at=timezone.now(),
            released_at=None,
        )

    def release(self, idempotency_key: str) -> None:
        WebhookEventRecord.objects.filter(
            idempotency_key=idempotency_key,
            status=WebhookEventRecord.Status.PROCESSING,
        ).update(
            status=WebhookEventRecord.Status.RELEASED,
            released_at=timezone.now(),
        )

    @staticmethod
    def _parse_idempotency_key(idempotency_key: str) -> tuple[str, str, str]:
        parts = idempotency_key.split(":", 2)
        if len(parts) != 3 or any(not part for part in parts):
            raise InvalidIdempotencyKeyError(
                "idempotency key must be tenant:provider:event"
            )

        tenant_slug, provider, provider_event_id = parts
        return tenant_slug, provider, provider_event_id

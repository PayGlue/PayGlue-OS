from datetime import timedelta

import pytest
from django.utils import timezone

from payglue_backend.core.errors import InvalidIdempotencyKeyError
from payglue_backend.webhooks.idempotency import DbIdempotencyStore
from payglue_backend.webhooks.models import WebhookEventRecord


@pytest.mark.django_db
def test_db_idempotency_start_then_processed_and_duplicate_denied() -> None:
    store = DbIdempotencyStore()
    key = "tenant-a:polar:evt_001"

    assert store.start_processing(key) is True
    store.mark_processed(key)
    assert store.start_processing(key) is False

    record = WebhookEventRecord.objects.get(idempotency_key=key)
    assert record.status == WebhookEventRecord.Status.PROCESSED
    assert record.processed_at is not None


@pytest.mark.django_db
def test_db_idempotency_release_allows_retry() -> None:
    store = DbIdempotencyStore()
    key = "tenant-a:polar:evt_retry"

    assert store.start_processing(key) is True
    store.release(key)
    assert store.start_processing(key) is True

    record = WebhookEventRecord.objects.get(idempotency_key=key)
    assert record.status == WebhookEventRecord.Status.PROCESSING


@pytest.mark.django_db
def test_db_idempotency_release_does_not_reopen_processed_event() -> None:
    store = DbIdempotencyStore()
    key = "tenant-a:polar:evt_processed"

    assert store.start_processing(key) is True
    store.mark_processed(key)
    store.release(key)

    assert store.start_processing(key) is False
    record = WebhookEventRecord.objects.get(idempotency_key=key)
    assert record.status == WebhookEventRecord.Status.PROCESSED


@pytest.mark.django_db
def test_db_idempotency_can_reclaim_stale_processing_lock() -> None:
    store = DbIdempotencyStore(processing_timeout_seconds=60)
    key = "tenant-a:polar:evt_stale"

    assert store.start_processing(key) is True
    stale_ts = timezone.now() - timedelta(minutes=10)
    WebhookEventRecord.objects.filter(idempotency_key=key).update(updated_at=stale_ts)

    assert store.start_processing(key) is True
    record = WebhookEventRecord.objects.get(idempotency_key=key)
    assert record.status == WebhookEventRecord.Status.PROCESSING


@pytest.mark.django_db
def test_db_idempotency_rejects_malformed_idempotency_key() -> None:
    store = DbIdempotencyStore()

    with pytest.raises(InvalidIdempotencyKeyError):
        store.start_processing("bad-format")

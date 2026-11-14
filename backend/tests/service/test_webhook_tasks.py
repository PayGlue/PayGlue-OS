import pytest
from datetime import timedelta
from django.test import override_settings
from django.utils import timezone

from payglue_backend.core.errors import (
    CmsApplyEntitlementError,
    InvalidWebhookSignatureError,
    MissingCredentialsError,
)
from payglue_backend.core.models import TenantContext
from payglue_backend.core.orchestrator import OrchestrationResult
from payglue_backend.tenants.models import Tenant
from payglue_backend.webhooks.models import IntegrationConfig
from payglue_backend.webhooks.models import WebhookInboundEvent
from payglue_backend.webhooks.tasks import process_inbound_webhook_event


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed_tenant_registry() -> None:
    Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_process_inbound_event_marks_processed_on_success(monkeypatch) -> None:
    class SuccessfulOrchestrator:
        def process_webhook(
            self,
            payment_provider_key: str,
            cms_provider_key: str,
            raw_body: bytes,
            headers: dict[str, str],
            tenant_ctx: TenantContext,
            skip_verification: bool = False,
            force: bool = False,
            on_verified=None,
        ) -> OrchestrationResult:
            assert payment_provider_key == "polar"
            assert cms_provider_key == "ghost"
            assert raw_body == b'{"id":"evt_1"}'
            assert headers["Content-Type"] == "application/json"
            assert tenant_ctx.tenant_slug == "tenant-a"
            return OrchestrationResult(
                status="processed", event_id="evt_1", applied_count=1
            )

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: SuccessfulOrchestrator(),
    )

    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.RECEIVED,
        payload_raw=b'{"id":"evt_1"}',
        headers_snapshot={"Content-Type": "application/json"},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/polar/endpoint-token/",
    )

    process_inbound_webhook_event.delay(event.id)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.PROCESSED
    assert event.attempts == 1
    assert event.last_error == ""


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_a_retry_does_not_verify_the_signature_again(monkeypatch) -> None:
    """The first attempt verifies. A retry runs after the backoff, and a
    provider that signs with a timestamp (Paddle allows about a minute) would
    fail that check on the clock alone, hiding the error the first attempt
    hit. Once the check has passed it is recorded, and the retry skips it."""
    seen: list[bool] = []

    class FailsOnceOrchestrator:
        def process_webhook(self, *, skip_verification: bool = False, on_verified=None, **kwargs) -> OrchestrationResult:
            seen.append(skip_verification)
            if on_verified is not None:
                on_verified()
            if len(seen) == 1:
                raise CmsApplyEntitlementError("ghost returned status 500")
            return OrchestrationResult(status="processed", event_id="evt_1", applied_count=1)

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: FailsOnceOrchestrator(),
    )
    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="paddle",
        status=WebhookInboundEvent.Status.RECEIVED,
        payload_raw=b"{}",
        headers_snapshot={"Paddle-Signature": "ts=1;h1=abc"},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/paddle/endpoint-token/",
    )

    process_inbound_webhook_event.delay(event.id)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.PROCESSED
    assert event.attempts == 2
    assert event.signature_verified is True
    assert seen == [False, True]


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_a_retry_verifies_again_when_the_first_attempt_never_passed_the_check(monkeypatch) -> None:
    """An error raised before the check passed proves nothing about the
    delivery. Skipping the check on the retry would apply a forged event that
    merely made the first attempt crash."""
    seen: list[bool] = []

    class CrashesBeforeTheCheckOrchestrator:
        def process_webhook(self, *, skip_verification: bool = False, on_verified=None, **kwargs) -> OrchestrationResult:
            seen.append(skip_verification)
            raise RuntimeError("unexpected error inside the check")

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: CrashesBeforeTheCheckOrchestrator(),
    )
    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="kofi",
        status=WebhookInboundEvent.Status.RECEIVED,
        payload_raw=b"{}",
        headers_snapshot={},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/kofi/endpoint-token/",
    )

    process_inbound_webhook_event.delay(event.id)

    event.refresh_from_db()
    assert seen == [False, False, False]
    assert event.signature_verified is False
    assert event.status == WebhookInboundEvent.Status.DEAD_LETTER


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def _stub_process(monkeypatch, outcome) -> list[bool]:
    seen: list[bool] = []

    class _Orchestrator:
        def process_webhook(self, **kwargs):
            seen.append(kwargs["skip_verification"])
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator", lambda: _Orchestrator()
    )
    return seen


def _received(**fields) -> WebhookInboundEvent:
    return WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.RECEIVED,
        payload_raw=b"{}",
        headers_snapshot={},
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
        **fields,
    )


def test_a_rejected_signature_is_recorded_on_the_event(monkeypatch) -> None:
    event = _received()
    _stub_process(monkeypatch, InvalidWebhookSignatureError("signature mismatch"))

    process_inbound_webhook_event(event.id, ignore_timing=True)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.FAILED
    assert event.verification_failed is True


def test_a_ghost_failure_does_not_count_as_unverified(monkeypatch) -> None:
    event = _received(max_attempts=1)
    _stub_process(monkeypatch, CmsApplyEntitlementError("ghost down"))

    process_inbound_webhook_event(event.id, ignore_timing=True)

    event.refresh_from_db()
    assert event.verification_failed is False


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_a_missing_secret_keeps_the_retry_verifying(monkeypatch) -> None:
    """The first attempt never reached the check, so the retry may not skip it."""
    event = _received()
    missing = MissingCredentialsError("tenant-a", "polar", ("webhook_secret",))
    seen = _stub_process(monkeypatch, missing)
    monkeypatch.setattr(
        "payglue_backend.webhooks.tasks.process_inbound_webhook_event.apply_async",
        lambda **kwargs: None,
    )

    process_inbound_webhook_event(event.id, ignore_timing=True)
    process_inbound_webhook_event(event.id, ignore_timing=True)

    assert seen == [False, False]


def test_a_passed_check_clears_the_mark(monkeypatch) -> None:
    event = _received(verification_failed=True)
    _stub_process(monkeypatch, OrchestrationResult(status="processed", event_id="evt-1", applied_count=1))

    process_inbound_webhook_event(event.id, ignore_timing=True)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.PROCESSED
    assert event.verification_failed is False


def test_a_duplicate_delivery_is_recorded_as_skipped_not_processed(monkeypatch) -> None:
    class DuplicateOrchestrator:
        def process_webhook(self, **kwargs) -> OrchestrationResult:
            return OrchestrationResult(status="duplicate", event_id="evt_1", applied_count=0)

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: DuplicateOrchestrator(),
    )
    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.RECEIVED,
        payload_raw=b"{}",
        headers_snapshot={},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/polar/endpoint-token/",
    )

    process_inbound_webhook_event.delay(event.id)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.SKIPPED
    assert "duplicate delivery" in event.last_error
    assert event.processed_at is None


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_a_replay_forces_the_run_but_its_retry_does_not(monkeypatch) -> None:
    """The replay takes over the idempotency record. If that run fails and is
    retried, the retry must not force again: the record was released on the
    failure, so it claims it normally, and a provider redelivery that slipped
    in between is not applied a second time."""
    seen: list[bool] = []

    class FailsOnceOrchestrator:
        def process_webhook(self, *, force: bool = False, **kwargs) -> OrchestrationResult:
            seen.append(force)
            if len(seen) == 1:
                raise CmsApplyEntitlementError("ghost returned status 500")
            return OrchestrationResult(status="processed", event_id="evt_1", applied_count=1)

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: FailsOnceOrchestrator(),
    )
    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.RECEIVED,
        payload_raw=b"{}",
        headers_snapshot={},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/polar/endpoint-token/",
    )

    process_inbound_webhook_event.delay(event.id, ignore_timing=True, skip_verification=True, force=True)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.PROCESSED
    assert seen == [True, False]


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_process_inbound_event_retries_then_dead_letters(monkeypatch) -> None:
    class FailingOrchestrator:
        def process_webhook(
            self,
            payment_provider_key: str,
            cms_provider_key: str,
            raw_body: bytes,
            headers: dict[str, str],
            tenant_ctx: TenantContext,
            skip_verification: bool = False,
            force: bool = False,
            on_verified=None,
        ) -> OrchestrationResult:
            del payment_provider_key, cms_provider_key, raw_body, headers, tenant_ctx
            raise CmsApplyEntitlementError("ghost unavailable")

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: FailingOrchestrator(),
    )

    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.RECEIVED,
        payload_raw=b'{"id":"evt_2"}',
        headers_snapshot={"Content-Type": "application/json"},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/polar/endpoint-token/",
    )

    process_inbound_webhook_event.delay(event.id)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.DEAD_LETTER
    assert event.attempts == 3
    assert event.last_error == "ghost unavailable"
    assert event.dead_lettered_at is not None


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_process_inbound_event_ignores_already_processing_events(monkeypatch) -> None:
    class ShouldNotRunOrchestrator:
        def process_webhook(
            self,
            payment_provider_key: str,
            cms_provider_key: str,
            raw_body: bytes,
            headers: dict[str, str],
            tenant_ctx: TenantContext,
            skip_verification: bool = False,
            force: bool = False,
            on_verified=None,
        ) -> OrchestrationResult:
            del payment_provider_key, cms_provider_key, raw_body, headers, tenant_ctx
            raise AssertionError("orchestrator should not run for processing event")

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: ShouldNotRunOrchestrator(),
    )

    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.PROCESSING,
        attempts=1,
        processing_started_at=timezone.now(),
        payload_raw=b"{}",
        headers_snapshot={"Content-Type": "application/json"},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
    )

    process_inbound_webhook_event.delay(event.id)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.PROCESSING
    assert event.attempts == 1


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, WEBHOOK_PROCESSING_TIMEOUT_SECONDS=60)
def test_process_inbound_event_recovers_stale_processing_events(monkeypatch) -> None:
    class SuccessfulOrchestrator:
        def process_webhook(
            self,
            payment_provider_key: str,
            cms_provider_key: str,
            raw_body: bytes,
            headers: dict[str, str],
            tenant_ctx: TenantContext,
            skip_verification: bool = False,
            force: bool = False,
            on_verified=None,
        ) -> OrchestrationResult:
            del payment_provider_key, cms_provider_key, raw_body, headers, tenant_ctx
            return OrchestrationResult(
                status="processed", event_id="evt_stale", applied_count=1
            )

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: SuccessfulOrchestrator(),
    )

    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.PROCESSING,
        attempts=1,
        processing_started_at=timezone.now() - timedelta(minutes=10),
        payload_raw=b"{}",
        headers_snapshot={"Content-Type": "application/json"},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
    )

    process_inbound_webhook_event.delay(event.id)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.PROCESSED
    assert event.attempts == 2


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_process_inbound_event_does_not_override_status_changed_by_other_worker(
    monkeypatch,
) -> None:
    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.RECEIVED,
        attempts=0,
        payload_raw=b"{}",
        headers_snapshot={"Content-Type": "application/json"},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
    )

    class RacingOrchestrator:
        def process_webhook(
            self,
            payment_provider_key: str,
            cms_provider_key: str,
            raw_body: bytes,
            headers: dict[str, str],
            tenant_ctx: TenantContext,
            skip_verification: bool = False,
            force: bool = False,
            on_verified=None,
        ) -> OrchestrationResult:
            del payment_provider_key, cms_provider_key, raw_body, headers, tenant_ctx
            WebhookInboundEvent.objects.filter(id=event.id).update(
                status=WebhookInboundEvent.Status.PROCESSED
            )
            raise CmsApplyEntitlementError("ghost unavailable")

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: RacingOrchestrator(),
    )

    process_inbound_webhook_event.delay(event.id)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.PROCESSED


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_process_inbound_event_fails_for_non_active_tenant(monkeypatch) -> None:
    Tenant.objects.filter(slug="tenant-a").update(status=Tenant.Status.SUSPENDED)

    class ShouldNotRunOrchestrator:
        def process_webhook(
            self,
            payment_provider_key: str,
            cms_provider_key: str,
            raw_body: bytes,
            headers: dict[str, str],
            tenant_ctx: TenantContext,
            skip_verification: bool = False,
            force: bool = False,
            on_verified=None,
        ) -> OrchestrationResult:
            del payment_provider_key, cms_provider_key, raw_body, headers, tenant_ctx
            raise AssertionError("orchestrator should not run for suspended tenant")

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: ShouldNotRunOrchestrator(),
    )

    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.RECEIVED,
        attempts=0,
        payload_raw=b"{}",
        headers_snapshot={"Content-Type": "application/json"},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
    )

    process_inbound_webhook_event.delay(event.id)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.FAILED
    assert event.last_error == "tenant is not active"


@override_settings(CELERY_TASK_ALWAYS_EAGER=False)
def test_process_inbound_event_marks_queue_publish_failure_on_retry_enqueue_error(
    monkeypatch,
) -> None:
    class FailingOrchestrator:
        def process_webhook(
            self,
            payment_provider_key: str,
            cms_provider_key: str,
            raw_body: bytes,
            headers: dict[str, str],
            tenant_ctx: TenantContext,
            skip_verification: bool = False,
            force: bool = False,
            on_verified=None,
        ) -> OrchestrationResult:
            del payment_provider_key, cms_provider_key, raw_body, headers, tenant_ctx
            raise CmsApplyEntitlementError("ghost unavailable")

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: FailingOrchestrator(),
    )

    def _raise_apply_async(*, kwargs: dict[str, object], countdown: int) -> None:
        del kwargs, countdown
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "payglue_backend.webhooks.tasks.process_inbound_webhook_event.apply_async",
        _raise_apply_async,
    )

    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.RECEIVED,
        attempts=0,
        payload_raw=b"{}",
        headers_snapshot={"Content-Type": "application/json"},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
    )

    process_inbound_webhook_event(event.id)

    event.refresh_from_db()
    assert event.status == WebhookInboundEvent.Status.DEAD_LETTER
    assert event.last_error == "queue publish failed"
    assert event.next_attempt_at is None


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
def test_process_inbound_event_uses_tenant_selected_cms_provider(monkeypatch) -> None:
    seen_cms_provider: list[str] = []

    class SuccessfulOrchestrator:
        def process_webhook(
            self,
            payment_provider_key: str,
            cms_provider_key: str,
            raw_body: bytes,
            headers: dict[str, str],
            tenant_ctx: TenantContext,
            skip_verification: bool = False,
            force: bool = False,
            on_verified=None,
        ) -> OrchestrationResult:
            del payment_provider_key, raw_body, headers, tenant_ctx
            seen_cms_provider.append(cms_provider_key)
            return OrchestrationResult(
                status="processed", event_id="evt_provider", applied_count=0
            )

    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="cms",
        provider_type="ghost",
        enabled=True,
        metadata={"site_url": "https://ghost.example.com"},
    )
    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.get_webhook_orchestrator",
        lambda: SuccessfulOrchestrator(),
    )

    event = WebhookInboundEvent.objects.create(
        tenant_slug="tenant-a",
        provider="polar",
        status=WebhookInboundEvent.Status.RECEIVED,
        payload_raw=b'{"id":"evt_3"}',
        headers_snapshot={"Content-Type": "application/json"},
        max_attempts=3,
        endpoint_path="/t/tenant-a/webhooks/polar/[redacted]/",
    )

    process_inbound_webhook_event.delay(event.id)

    assert seen_cms_provider == ["ghost"]

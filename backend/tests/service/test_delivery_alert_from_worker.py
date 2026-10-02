# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-319: the creator hears about a stuck purchase from the worker, on the
first terminal failure, with the template that matches the cause. One mail per
incident; the next processed event clears it.

PG-326: a mail that cannot go out leaves the incident PENDING with the reason,
and the alert no longer depends on a Ghost connection existing."""

import pytest
from django.core import mail

from payglue_backend.core.errors import (
    CmsApplyEntitlementError,
    InvalidWebhookSignatureError,
    MissingCredentialsError,
)
from payglue_backend.tenants.models import (
    LifecycleEmailTemplate,
    Tenant,
    TenantMembership,
    UserProfile,
)
from payglue_backend.webhooks import delivery_alerts, tasks
from payglue_backend.webhooks.models import (
    DeliveryAlert,
    IntegrationConfig,
    WebhookInboundEvent,
)


@pytest.fixture(autouse=True)
def _dashboard_address(settings):
    settings.PUBLIC_APP_BASE_URL = "https://dashboard.example.com"
    settings.CELERY_TASK_ALWAYS_EAGER = True


pytestmark = pytest.mark.django_db

_S = WebhookInboundEvent.Status


def _tenant_with_owner(slug: str = "acme", email: str = "owner@example.com") -> Tenant:
    tenant = Tenant.objects.create(slug=slug, schema_name=slug.replace("-", "_"))
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    TenantMembership.objects.create(
        tenant=tenant, user_profile=owner, role=TenantMembership.Role.OWNER
    )
    IntegrationConfig.objects.create(
        tenant_slug=slug,
        provider_key="cms",
        enabled=True,
        provider_type="ghost",
        metadata={},
    )
    return tenant


def _event(slug: str = "acme", provider: str = "creem") -> WebhookInboundEvent:
    return WebhookInboundEvent.objects.create(
        tenant_slug=slug,
        provider=provider,
        status=_S.RECEIVED,
        payload_raw=b"{}",
        headers_snapshot={"Content-Type": "application/json"},
        endpoint_path=f"/webhooks/{provider}",
    )


class _Orchestrator:
    def __init__(self, error: Exception | None) -> None:
        self.error = error

    def process_webhook(self, **kwargs) -> None:
        if self.error is not None:
            raise self.error


def _run(
    monkeypatch, event: WebhookInboundEvent, error: Exception | None
) -> WebhookInboundEvent:
    monkeypatch.setattr(
        tasks.wiring, "get_webhook_orchestrator", lambda: _Orchestrator(error)
    )
    monkeypatch.setattr(
        tasks.wiring, "get_tenant_cms_provider_key", lambda slug: "ghost"
    )
    tasks.process_inbound_webhook_event(event.id, ignore_timing=True)
    event.refresh_from_db()
    return event


def _alert(slug: str = "acme") -> DeliveryAlert | None:
    return DeliveryAlert.objects.filter(tenant_slug=slug).first()


def test_signature_failure_mails_the_provider_template_at_once(monkeypatch) -> None:
    _tenant_with_owner()
    event = _run(
        monkeypatch,
        _event(),
        InvalidWebhookSignatureError("missing creem-signature header"),
    )

    assert event.status == _S.FAILED
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == ["owner@example.com"]
    assert sent.subject == "PayGlue: Creem webhooks for acme are being rejected"
    assert "1 event(s) since" in sent.body
    assert "https://dashboard.example.com/t/acme/connection/creem" in sent.body
    assert _alert().state == "failing"
    assert _alert().kind == "provider"
    assert _alert().notified_at is not None
    assert _alert().last_send_error == ""


def test_ghost_failure_mails_the_ghost_template_when_retries_are_exhausted(
    monkeypatch,
) -> None:
    _tenant_with_owner()
    event = _event(provider="polar")
    WebhookInboundEvent.objects.filter(pk=event.pk).update(max_attempts=1)
    event = _run(
        monkeypatch, event, CmsApplyEntitlementError("ghost member lookup failed")
    )

    assert event.status == _S.DEAD_LETTER
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.subject == "PayGlue: Your Ghost connection is failing"
    assert "https://dashboard.example.com/t/acme/connection/ghost" in sent.body
    assert "Replay" in sent.body
    assert _alert().kind == "ghost"


def test_retry_in_progress_does_not_mail_yet(monkeypatch) -> None:
    """A retryable error with attempts left is not terminal. The creator is
    told when the last attempt fails, not on the first blip."""
    _tenant_with_owner()
    event = _event(provider="polar")
    # Keep the retry from running inline so the state after the first attempt is observable.
    monkeypatch.setattr(
        tasks.process_inbound_webhook_event, "delay", lambda *a, **k: None
    )
    event = _run(monkeypatch, event, CmsApplyEntitlementError("ghost down"))

    assert event.status == _S.FAILED
    assert event.next_attempt_at is not None
    assert len(mail.outbox) == 0
    assert _alert() is None


def test_second_failure_in_the_same_incident_is_silent(monkeypatch) -> None:
    _tenant_with_owner()
    _run(monkeypatch, _event(), InvalidWebhookSignatureError("bad"))
    _run(monkeypatch, _event(), InvalidWebhookSignatureError("bad"))

    assert len(mail.outbox) == 1


def test_processed_event_clears_the_incident_so_the_next_one_mails_again(
    monkeypatch,
) -> None:
    _tenant_with_owner()
    _run(monkeypatch, _event(), InvalidWebhookSignatureError("bad"))
    _run(monkeypatch, _event(), None)
    assert _alert().state == "healthy"

    _run(monkeypatch, _event(), InvalidWebhookSignatureError("bad again"))
    assert len(mail.outbox) == 2


def test_count_and_since_cover_the_failures_since_the_last_success(monkeypatch) -> None:
    _tenant_with_owner()
    _run(monkeypatch, _event(), None)
    # Three failures land before anyone is told (state was cleared, alert
    # would fire on the first; simulate a disabled template for two of them).
    LifecycleEmailTemplate.objects.filter(trigger="provider_webhook_failing").update(
        enabled=False
    )
    _run(monkeypatch, _event(), InvalidWebhookSignatureError("bad"))
    _run(monkeypatch, _event(), InvalidWebhookSignatureError("bad"))
    assert _alert().state == "pending"
    assert "switched off" in _alert().last_send_error
    LifecycleEmailTemplate.objects.filter(trigger="provider_webhook_failing").update(
        enabled=True
    )
    _run(monkeypatch, _event(), InvalidWebhookSignatureError("bad"))

    assert len(mail.outbox) == 1
    assert "3 event(s) since" in mail.outbox[0].body
    assert _alert().state == "failing"
    assert _alert().send_attempts == 3


def test_missing_ghost_credentials_count_as_a_ghost_problem() -> None:
    err = MissingCredentialsError(
        tenant_slug="acme", provider_key="ghost", missing_fields=("admin_api_key",)
    )
    assert delivery_alerts.classify_failure(err) == delivery_alerts.KIND_GHOST
    err = MissingCredentialsError(
        tenant_slug="acme", provider_key="creem", missing_fields=("webhook_secret",)
    )
    assert delivery_alerts.classify_failure(err) == delivery_alerts.KIND_PROVIDER


def test_a_publication_without_a_ghost_connection_is_told_too(monkeypatch) -> None:
    """PG-326: the state used to hang off the Ghost connection, so a half
    finished setup, the case that needs the alert most, never got one."""
    _tenant_with_owner()
    IntegrationConfig.objects.filter(tenant_slug="acme").delete()
    _run(
        monkeypatch,
        _event(provider="polar"),
        MissingCredentialsError(
            tenant_slug="acme", provider_key="ghost", missing_fields=("admin_api_key",)
        ),
    )

    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "PayGlue: Your Ghost connection is failing"
    assert _alert().state == "failing"


def test_no_owner_leaves_the_incident_pending_with_the_reason(monkeypatch) -> None:
    Tenant.objects.create(slug="lonely", schema_name="lonely")
    _run(monkeypatch, _event(slug="lonely"), InvalidWebhookSignatureError("bad"))

    assert len(mail.outbox) == 0
    assert _alert("lonely").state == "pending"
    assert "no owner" in _alert("lonely").last_send_error


def test_missing_provider_credentials_that_run_into_the_dead_letter_mail_the_owner(
    monkeypatch,
) -> None:
    """The case PG-326 was opened for: a creator registers the webhook at
    Patreon, never saves the credentials in PayGlue, and the events retry their
    way into the dead letter queue."""
    _tenant_with_owner()
    event = _event(provider="patreon")
    WebhookInboundEvent.objects.filter(pk=event.pk).update(max_attempts=1)
    event = _run(
        monkeypatch,
        event,
        MissingCredentialsError(
            tenant_slug="acme",
            provider_key="patreon",
            missing_fields=("provider credentials",),
        ),
    )

    assert event.status == _S.DEAD_LETTER
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.subject == "PayGlue: Patreon webhooks for acme are being rejected"
    assert "https://dashboard.example.com/t/acme/connection/patreon" in sent.body
    assert _alert().state == "failing"
    assert _alert().kind == "provider"
    assert _alert().provider == "patreon"


def test_a_mail_backend_without_credentials_leaves_a_trace(monkeypatch, settings) -> None:
    """A worker without RESEND_API_KEY. The backend raises and the sender
    swallows it. The incident still has to be on record, with the backend's
    own words."""
    settings.EMAIL_BACKEND = "payglue_backend.core.email_backend.ResendAPIEmailBackend"
    settings.RESEND_API_KEY = ""
    _tenant_with_owner()
    event = _run(monkeypatch, _event(provider="patreon"), InvalidWebhookSignatureError("bad"))

    assert event.status == _S.FAILED
    alert = _alert()
    assert alert.state == "pending"
    assert "RESEND_API_KEY is not set" in alert.last_send_error
    assert alert.send_attempts == 1
    assert alert.notified_at is None


def test_alerting_failure_never_breaks_the_event(monkeypatch) -> None:
    _tenant_with_owner()

    def boom(*a, **k):
        raise RuntimeError("mail server on fire")

    monkeypatch.setattr("payglue_backend.authn.lifecycle_emails._send_branded", boom)
    event = _run(monkeypatch, _event(), InvalidWebhookSignatureError("bad"))

    assert event.status == _S.FAILED
    assert event.last_error == "bad"
    assert _alert().state == "pending"
    assert "mail server on fire" in _alert().last_send_error

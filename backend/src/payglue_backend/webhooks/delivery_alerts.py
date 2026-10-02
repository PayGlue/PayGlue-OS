# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Tell the creator the moment a purchase stops reaching Ghost, and tell the
operator only when the creator has not fixed it two days later.

The first version of this alert (PG-192) lived in the nightly job and asked
for three failed deliveries inside 24 hours. A creator with one sale a day
never reaches that, so a tenant sat on eight failed purchases for four weeks
without a single mail (PG-318). This version fires from the worker, on the
first delivery that ends in a terminal failure, and knows two causes:

- ghost: PayGlue could not write to the creator's Ghost site. Rotated Admin
  API key, Ghost unreachable, missing Ghost credentials. The creator can fix
  it on the Ghost connection page.
- provider: the payment provider's webhook could not be trusted or read.
  Wrong webhook secret, missing signature, malformed payload. The creator
  compares the secret on the provider's connection page; if it matches, the
  fault is ours and the mail says so.

Dedup is one DeliveryAlert row per tenant: one mail on the healthy -> failing
transition, a reset on the next processed event, nothing in between. The
operator is not copied on the creator's mail (a support mail arriving together
with the system's error reads as pressure). The nightly job escalates once,
internally, when a tenant has been failing for ESCALATE_AFTER_HOURS without a
processed event since.

A mail that cannot be sent is not the end of the incident (PG-326). The state
used to be written only after a successful send, and it lived on the Ghost
connection. A worker without mail credentials raises inside the mail backend,
the sender logs that and returns, and nothing was left behind: no state, no
retry, no escalation, only a log line. Now the failure is recorded first, as
PENDING with the reason, and the nightly job, which runs in a different
process with its own configuration, retries it. A tenant without a Ghost connection is covered too, because the
row no longer hangs off that connection.

Everything here is best effort: a failure to alert is recorded and never
changes what happens to the webhook event itself.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from payglue_backend.core.errors import (
    CmsApplyEntitlementError,
    MissingCredentialsError,
)
from payglue_backend.webhooks.models import DeliveryAlert, WebhookInboundEvent

logger = logging.getLogger(__name__)

KIND_GHOST = "ghost"
KIND_PROVIDER = "provider"

ESCALATE_AFTER_HOURS = 48

# How far back the "since" date and the failure count look when the first
# failure is recorded. Keeps the count honest for a tenant whose old failures
# were resolved by hand long ago.
_LOOKBACK_DAYS = 30

_Status = WebhookInboundEvent.Status
_FAILURE = (_Status.FAILED, _Status.DEAD_LETTER)

PROVIDER_NAMES = {
    "polar": "Polar",
    "lemonsqueezy": "Lemon Squeezy",
    "paypal": "PayPal",
    "gumroad": "Gumroad",
    "paddle": "Paddle",
    "kofi": "Ko-fi",
    "creem": "Creem",
    "patreon": "Patreon",
}


def provider_display_name(provider_key: str) -> str:
    return PROVIDER_NAMES.get(
        provider_key, provider_key.capitalize() or "your payment provider"
    )


def classify_failure(error: Exception) -> str:
    """ghost when the write to Ghost failed, provider for everything that went
    wrong before that: signature, payload, customer identity."""
    if isinstance(error, CmsApplyEntitlementError):
        return KIND_GHOST
    if isinstance(error, MissingCredentialsError):
        provider_key = getattr(error, "provider_key", "") or ""
        if provider_key in ("ghost", "cms"):
            return KIND_GHOST
        return KIND_PROVIDER
    return KIND_PROVIDER


def _owner_email(tenant_slug: str) -> str | None:
    from payglue_backend.tenants.models import TenantMembership

    membership = (
        TenantMembership.objects.filter(
            tenant__slug=tenant_slug, role=TenantMembership.Role.OWNER
        )
        .select_related("user_profile")
        .first()
    )
    return membership.user_profile.email if membership else None


def _failures_since_last_success(tenant_slug: str) -> tuple[int, str]:
    """Count of terminal failures after the tenant's last processed event
    (or within the lookback window), and the date of the first of them."""
    since = timezone.now() - timedelta(days=_LOOKBACK_DAYS)
    last_ok = (
        WebhookInboundEvent.objects.filter(
            tenant_slug=tenant_slug, status=_Status.PROCESSED
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if last_ok and last_ok > since:
        since = last_ok
    failures = WebhookInboundEvent.objects.filter(
        tenant_slug=tenant_slug, status__in=_FAILURE, created_at__gt=since
    ).order_by("created_at")
    count = failures.count()
    first = failures.values_list("created_at", flat=True).first()
    first_date = (first or timezone.now()).strftime("%d %b %Y")
    return max(count, 1), first_date


def _notify(alert: DeliveryAlert) -> bool:
    """One attempt to tell the creator. Writes the outcome on the row either
    way: FAILING with a timestamp when the mail went out, PENDING with the
    reason when it did not. The caller holds the row lock."""
    from payglue_backend.authn.lifecycle_emails import send_delivery_failure_alert

    count, since = _failures_since_last_success(alert.tenant_slug)
    alert.failure_count = count
    alert.failing_since = since
    alert.send_attempts += 1

    sent = False
    reason = ""
    owner = _owner_email(alert.tenant_slug)
    if not owner:
        reason = "the publication has no owner with an email address"
    else:
        errors: list[str] = []
        try:
            sent = send_delivery_failure_alert(
                owner,
                tenant_slug=alert.tenant_slug,
                kind=alert.kind or KIND_PROVIDER,
                provider_key=alert.provider,
                count=count,
                since=since,
                errors=errors,
            )
        except Exception as exc:  # the sender is fail-safe; this is the belt
            errors.append(f"{type(exc).__name__}: {exc}")
        if not sent:
            reason = errors[0] if errors else "the mail was not sent"

    if sent:
        alert.state = DeliveryAlert.State.FAILING
        alert.notified_at = timezone.now()
        alert.last_send_error = ""
    else:
        alert.state = DeliveryAlert.State.PENDING
        alert.last_send_error = reason[:2000]
        logger.error(
            "delivery alert: %s could not be told (%s), left pending for the nightly run",
            alert.tenant_slug,
            reason,
        )
    alert.save()
    return sent


def record_delivery_failure(event: WebhookInboundEvent, error: Exception) -> bool:
    """Called by the worker after an event ended in FAILED (no retry left) or
    DEAD_LETTER. Mails the owner once per incident. Returns True when a mail
    went out. When it could not go out, the incident stays PENDING with the
    reason and the nightly job tries again."""
    try:
        with transaction.atomic():
            DeliveryAlert.objects.get_or_create(tenant_slug=event.tenant_slug)
            # Two purchases can reach their last attempt in the same second.
            # The lock makes the second one see what the first one decided,
            # so the creator gets one mail and not two.
            alert = DeliveryAlert.objects.select_for_update().get(
                tenant_slug=event.tenant_slug
            )
            if alert.state == DeliveryAlert.State.FAILING:
                return False
            if alert.state == DeliveryAlert.State.HEALTHY:
                alert.first_failed_at = timezone.now()
                alert.notified_at = None
                alert.escalated_at = None
                alert.send_attempts = 0
                alert.last_send_error = ""
            alert.kind = classify_failure(error)
            alert.provider = event.provider
            return _notify(alert)
    except Exception:
        logger.exception(
            "delivery alert: failed to record failure for %s", event.tenant_slug
        )
        return False


def retry_pending(tenant_slug: str) -> bool:
    """The nightly job's second chance for an incident the worker could not
    mail. Returns True when the creator has now been told."""
    try:
        with transaction.atomic():
            alert = (
                DeliveryAlert.objects.select_for_update()
                .filter(tenant_slug=tenant_slug, state=DeliveryAlert.State.PENDING)
                .first()
            )
            if alert is None:
                return False
            return _notify(alert)
    except Exception:
        logger.exception("delivery alert: retry failed for %s", tenant_slug)
        return False


def record_delivery_success(tenant_slug: str) -> None:
    """Called by the worker after a processed event. Clears the incident so
    the next failure mails again. No recovery mail, no nagging."""
    try:
        DeliveryAlert.objects.filter(tenant_slug=tenant_slug).exclude(
            state=DeliveryAlert.State.HEALTHY
        ).update(state=DeliveryAlert.State.HEALTHY, updated_at=timezone.now())
    except Exception:
        logger.exception(
            "delivery alert: failed to record recovery for %s", tenant_slug
        )

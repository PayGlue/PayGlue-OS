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

Dedup is a small state on the Ghost IntegrationConfig's metadata, as before:
one mail on the healthy -> failing transition, a reset on the next processed
event, nothing in between. The operator is not copied on the creator's mail
(a support mail arriving together with the system's error reads as pressure).
The nightly job escalates once, internally, when a tenant has been failing
for ESCALATE_AFTER_HOURS without a processed event since.

Everything here is best effort: a failure to alert is logged and never
changes what happens to the webhook event itself.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from payglue_backend.core.errors import (
    CmsApplyEntitlementError,
    MissingCredentialsError,
)
from payglue_backend.webhooks.models import IntegrationConfig, WebhookInboundEvent

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


def _ghost_config(tenant_slug: str) -> IntegrationConfig | None:
    return IntegrationConfig.objects.filter(
        tenant_slug=tenant_slug, provider_key="cms", enabled=True
    ).first()


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


def record_delivery_failure(event: WebhookInboundEvent, error: Exception) -> bool:
    """Called by the worker after an event ended in FAILED (no retry left) or
    DEAD_LETTER. Mails the owner once per incident. Returns True when a mail
    went out."""
    try:
        config = _ghost_config(event.tenant_slug)
        if config is None:
            return False
        metadata = config.metadata or {}
        state = metadata.get("delivery_alert") or {}
        if state.get("state") == "failing":
            return False

        owner = _owner_email(event.tenant_slug)
        if not owner:
            logger.info(
                "delivery alert: %s failing but has no owner email", event.tenant_slug
            )
            return False

        kind = classify_failure(error)
        count, since = _failures_since_last_success(event.tenant_slug)
        from payglue_backend.authn.lifecycle_emails import send_delivery_failure_alert

        sent = send_delivery_failure_alert(
            owner,
            tenant_slug=event.tenant_slug,
            kind=kind,
            provider_key=event.provider,
            count=count,
            since=since,
        )
        if not sent:
            return False
        metadata["delivery_alert"] = {
            "state": "failing",
            "kind": kind,
            "provider": event.provider,
            "notified_at": timezone.now().isoformat(),
            "since": since,
            "count": count,
            "escalated_at": None,
        }
        config.metadata = metadata
        config.save(update_fields=["metadata", "updated_at"])
        return True
    except Exception:
        logger.exception(
            "delivery alert: failed to record failure for %s", event.tenant_slug
        )
        return False


def record_delivery_success(tenant_slug: str) -> None:
    """Called by the worker after a processed event. Clears the incident so
    the next failure mails again. No recovery mail, no nagging."""
    try:
        config = _ghost_config(tenant_slug)
        if config is None:
            return
        metadata = config.metadata or {}
        state = metadata.get("delivery_alert") or {}
        if state.get("state") != "failing":
            return
        metadata["delivery_alert"] = {"state": "healthy"}
        config.metadata = metadata
        config.save(update_fields=["metadata", "updated_at"])
    except Exception:
        logger.exception(
            "delivery alert: failed to record recovery for %s", tenant_slug
        )

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from typing import Callable, Mapping

from payglue_backend.core.errors import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    MissingCredentialsError,
    UnsupportedEventTypeError,
)
from payglue_backend.core.interfaces import CredentialProvider
from payglue_backend.core.models import (
    CanonicalCustomer,
    CanonicalLineItem,
    CanonicalPaymentEvent,
    TenantContext,
)

# Gumroad's `sale` resource fires on every charge (first purchase and every
# recurring renewal alike) -- there's no separate "renewal" event, so both
# map to order.paid, matching how the other adapters treat their `sale`-like
# webhooks. Subscription lifecycle resources are delivered to the same
# post_url as separate resource_subscriptions and are distinguished by which
# fields are present in the payload rather than an explicit event name.
_SUPPORTED_EVENTS = {"order.paid", "subscription.canceled", "subscription.revoked"}

_TRUE_STRINGS = {"true", "1", "yes"}


class GumroadPaymentAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider,
        provider_key: str = "gumroad",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._supported_events = set(_SUPPORTED_EVENTS)

    def health_check(self, tenant_ctx: TenantContext) -> dict[str, object]:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        access_token = credentials.get("access_token")
        application_secret = credentials.get("application_secret")
        missing = [
            f
            for f, v in [
                ("access_token", access_token),
                ("application_secret", application_secret),
            ]
            if not v
        ]
        if missing:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=tuple(missing),
            )

        req = urllib.request.Request(
            f"https://api.gumroad.com/v2/user?access_token={access_token}",
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=(),
            ) from e
        except Exception as e:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=(),
            ) from e

        if not data.get("success"):
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=(),
            )

        return {
            "ok": True,
            "code": "ok",
            "message": "Gumroad access token verified successfully.",
        }

    # Gumroad has no dashboard UI for registering a webhook -- unlike
    # Polar/PayPal/LemonSqueezy, where the merchant pastes the webhook URL
    # into a settings page on the provider's own site. A real PayGlue user
    # will never call Gumroad's resource_subscriptions API by hand, so we
    # call it for them, server-side, the moment they save an access token.
    # Re-registering on every save is safe: Gumroad's own API is what we're
    # calling (not something we can dedupe client-side), and any resulting
    # duplicate deliveries are already deduped by the orchestrator's
    # idempotency store keyed on provider_event_id.
    _WEBHOOK_RESOURCE_NAMES = ("sale", "cancellation", "subscription_ended")

    def register_webhook_subscriptions(
        self, tenant_ctx: TenantContext, webhook_url: str
    ) -> dict[str, object]:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        access_token = credentials.get("access_token")
        if not access_token:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("access_token",),
            )

        registered: list[str] = []
        failed: list[str] = []
        for resource_name in self._WEBHOOK_RESOURCE_NAMES:
            body = urlencode(
                {
                    "access_token": access_token,
                    "resource_name": resource_name,
                    "post_url": webhook_url,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                "https://api.gumroad.com/v2/resource_subscriptions",
                data=body,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                if data.get("success"):
                    registered.append(resource_name)
                else:
                    failed.append(resource_name)
            except Exception:
                failed.append(resource_name)

        return {"registered": registered, "failed": failed}

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> None:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        application_secret = credentials.get("application_secret")
        if not application_secret:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("application_secret",),
            )

        signature = None
        for key, value in headers.items():
            if key.lower() == "x-gumroad-signature":
                signature = value
                break

        # Confirmed against a real purchase (2026-07-03): Gumroad does not
        # sign resource_subscriptions deliveries. Verify the signature if
        # Gumroad ever sends one, but don't require it -- the per-tenant
        # webhook URL itself is the only secret Gumroad actually gives us.
        if signature is None:
            return

        expected = hmac.new(
            application_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            raise InvalidWebhookSignatureError("signature mismatch")

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> CanonicalPaymentEvent:
        payload = self._decode_payload(raw_body, headers)

        email = payload.get("email")
        if not email:
            raise InvalidWebhookPayloadError("missing email")

        sale_id = payload.get("sale_id")
        subscription_id = payload.get("subscription_id")
        product_id = payload.get("product_id") or payload.get("permalink")

        if sale_id:
            return self._parse_sale(payload, email, sale_id, product_id)
        if subscription_id and self._is_truthy(payload.get("cancelled")):
            return self._parse_lifecycle(
                payload, email, subscription_id, product_id, "subscription.canceled"
            )
        if subscription_id and self._is_truthy(payload.get("ended")):
            return self._parse_lifecycle(
                payload, email, subscription_id, product_id, "subscription.revoked"
            )

        raise UnsupportedEventTypeError(
            "gumroad payload did not match a known sale or subscription-lifecycle shape"
        )

    def _parse_sale(
        self, payload: dict, email: str, sale_id: str, product_id: str | None
    ) -> CanonicalPaymentEvent:
        currency = (payload.get("currency") or "usd").upper()
        try:
            amount_minor = int(payload.get("price", 0))
        except (TypeError, ValueError):
            amount_minor = 0

        occurred_at = self._parse_timestamp(payload.get("sale_timestamp"))

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=str(sale_id),
            event_type="order.paid",
            occurred_at=occurred_at,
            customer=CanonicalCustomer(email=email, external_id=payload.get("purchaser_id")),
            line_items=(
                CanonicalLineItem(
                    external_product_id=str(product_id or sale_id),
                    quantity=int(payload.get("quantity", 1) or 1),
                    amount_minor=amount_minor,
                    currency=currency,
                ),
            ),
            status="paid",
        )

    def _parse_lifecycle(
        self,
        payload: dict,
        email: str,
        subscription_id: str,
        product_id: str | None,
        canonical_type: str,
    ) -> CanonicalPaymentEvent:
        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=str(subscription_id),
            event_type=canonical_type,
            occurred_at=self._now(),
            customer=CanonicalCustomer(email=email),
            line_items=(
                CanonicalLineItem(
                    external_product_id=str(product_id or subscription_id),
                    quantity=1,
                    amount_minor=0,
                    currency="USD",
                ),
            ),
            status="canceled" if canonical_type == "subscription.canceled" else "revoked",
        )

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._supported_events

    @staticmethod
    def _decode_payload(raw_body: bytes, headers: Mapping[str, str]) -> dict:
        content_type = ""
        for key, value in headers.items():
            if key.lower() == "content-type":
                content_type = value.lower()
                break

        if "application/json" in content_type:
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                raise InvalidWebhookPayloadError("payload is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise InvalidWebhookPayloadError("payload must be a JSON object")
            return payload

        try:
            pairs = parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError as exc:
            raise InvalidWebhookPayloadError("payload is not valid form data") from exc
        if not pairs:
            raise InvalidWebhookPayloadError("empty payload")
        return dict(pairs)

    @staticmethod
    def _is_truthy(value: object) -> bool:
        return isinstance(value, str) and value.lower() in _TRUE_STRINGS

    def _parse_timestamp(self, value: object) -> datetime:
        if isinstance(value, str) and value:
            try:
                parsed = value[:-1] + "+00:00" if value.endswith("Z") else value
                dt = datetime.fromisoformat(parsed)
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
            except ValueError:
                pass
        return self._now()

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from datetime import UTC, datetime, timedelta
import base64
import json
import urllib.request
import urllib.error
from threading import Lock
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

_EVENT_MAP = {
    "BILLING.SUBSCRIPTION.ACTIVATED": "subscription.active",
    "BILLING.SUBSCRIPTION.UPDATED": "subscription.active",
    "BILLING.SUBSCRIPTION.RE-ACTIVATED": "subscription.active",
    "BILLING.SUBSCRIPTION.CANCELLED": "subscription.canceled",
    "BILLING.SUBSCRIPTION.SUSPENDED": "subscription.canceled",
    "BILLING.SUBSCRIPTION.EXPIRED": "subscription.revoked",
    "PAYMENT.CAPTURE.COMPLETED": "order.paid",
}

_TOKEN_BUFFER_SECONDS = 300  # refresh 5 min before expiry


class PayPalPaymentAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider,
        provider_key: str = "paypal",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._raw_event_names = set(_EVENT_MAP.keys())
        self._supported_events = set(_EVENT_MAP.values())
        self._token_cache: dict[str, tuple[str, datetime]] = {}
        self._token_lock = Lock()

    def _base_url(self, sandbox: bool) -> str:
        return "https://api-m.sandbox.paypal.com" if sandbox else "https://api-m.paypal.com"

    def _get_oauth_token(self, client_id: str, client_secret: str, sandbox: bool) -> str:
        cache_key = f"{client_id}:{sandbox}"
        with self._token_lock:
            cached = self._token_cache.get(cache_key)
            if cached:
                token, expires_at = cached
                if self._now() < expires_at - timedelta(seconds=_TOKEN_BUFFER_SECONDS):
                    return token

        credentials_b64 = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        req = urllib.request.Request(
            f"{self._base_url(sandbox)}/v1/oauth2/token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {credentials_b64}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise InvalidWebhookSignatureError(f"PayPal OAuth failed: HTTP {e.code}") from e
        except Exception as e:
            raise InvalidWebhookSignatureError(f"PayPal OAuth error: {e}") from e

        token = data.get("access_token")
        expires_in = int(data.get("expires_in", 32400))
        if not token:
            raise InvalidWebhookSignatureError("PayPal OAuth returned no access_token")

        expires_at = self._now() + timedelta(seconds=expires_in)
        with self._token_lock:
            self._token_cache[cache_key] = (token, expires_at)
        return token

    def health_check(self, tenant_ctx: TenantContext) -> dict[str, object]:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        missing = [f for f, v in [("client_id", client_id), ("client_secret", client_secret)] if not v]
        if missing:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=tuple(missing),
            )
        sandbox = credentials.get("sandbox", "") in ("true", "1", True)
        try:
            self._get_oauth_token(client_id, client_secret, sandbox)
        except InvalidWebhookSignatureError as exc:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=(),
            ) from exc
        return {
            "ok": True,
            "code": "ok",
            "message": "PayPal credentials verified. OAuth token obtained successfully.",
        }

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> None:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        webhook_id = credentials.get("webhook_id")

        missing = [f for f, v in [("client_id", client_id), ("client_secret", client_secret)] if not v]
        if missing:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=tuple(missing),
            )
        if not webhook_id:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("webhook_id",),
            )

        sandbox = credentials.get("sandbox", "") in ("true", "1", True)
        h = {k.lower(): v for k, v in headers.items()}
        transmission_id = h.get("paypal-transmission-id")
        transmission_time = h.get("paypal-transmission-time")
        cert_url = h.get("paypal-cert-url")
        auth_algo = h.get("paypal-auth-algo")
        transmission_sig = h.get("paypal-transmission-sig")

        if not all([transmission_id, transmission_time, cert_url, auth_algo, transmission_sig]):
            raise InvalidWebhookSignatureError("Missing required PayPal webhook headers")

        token = self._get_oauth_token(client_id, client_secret, sandbox)

        verify_body = json.dumps({
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": transmission_sig,
            "transmission_time": transmission_time,
            "webhook_id": webhook_id,
            "webhook_event": json.loads(raw_body),
        }).encode()

        req = urllib.request.Request(
            f"{self._base_url(sandbox)}/v1/notifications/verify-webhook-signature",
            data=verify_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise InvalidWebhookSignatureError(f"PayPal verify API failed: HTTP {e.code}") from e
        except Exception as e:
            raise InvalidWebhookSignatureError(f"PayPal verify API error: {e}") from e

        if result.get("verification_status") != "SUCCESS":
            raise InvalidWebhookSignatureError(
                f"PayPal webhook verification failed: {result.get('verification_status')}"
            )

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> CanonicalPaymentEvent:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise InvalidWebhookPayloadError("payload is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise InvalidWebhookPayloadError("payload must be a JSON object")

        event_type = payload.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            raise InvalidWebhookPayloadError("missing event_type")

        if event_type not in self._raw_event_names:
            raise UnsupportedEventTypeError(event_type)

        canonical_type = _EVENT_MAP[event_type]
        event_id = str(payload.get("id", ""))
        if not event_id:
            raise InvalidWebhookPayloadError("missing event id")

        resource = payload.get("resource")
        if not isinstance(resource, dict):
            raise InvalidWebhookPayloadError("missing resource object")

        occurred_at = self._now()
        raw_time = payload.get("create_time") or resource.get("create_time")
        if isinstance(raw_time, str) and raw_time:
            try:
                occurred_at = self._parse_iso8601(raw_time)
            except InvalidWebhookPayloadError:
                pass

        if event_type.startswith("BILLING.SUBSCRIPTION."):
            return self._parse_subscription(resource, event_id, canonical_type, occurred_at)
        return self._parse_capture(resource, event_id, canonical_type, occurred_at)

    def _parse_subscription(
        self, resource: dict, event_id: str, canonical_type: str, occurred_at: datetime
    ) -> CanonicalPaymentEvent:
        plan_id = resource.get("plan_id")
        if not plan_id:
            raise InvalidWebhookPayloadError("missing plan_id in subscription resource")

        subscriber = resource.get("subscriber") or {}
        email = subscriber.get("email_address")
        if not email:
            raise InvalidWebhookPayloadError("missing subscriber.email_address")

        name_obj = subscriber.get("name") or {}
        full_name = f"{name_obj.get('given_name', '')} {name_obj.get('surname', '')}".strip() or None

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type=canonical_type,
            occurred_at=occurred_at,
            customer=CanonicalCustomer(
                email=email,
                external_id=resource.get("id"),
                name=full_name,
            ),
            line_items=(
                CanonicalLineItem(
                    external_product_id=str(plan_id),
                    quantity=1,
                    amount_minor=0,
                    currency="USD",
                ),
            ),
            status=resource.get("status", "active").lower(),
        )

    def _parse_capture(
        self, resource: dict, event_id: str, canonical_type: str, occurred_at: datetime
    ) -> CanonicalPaymentEvent:
        # PayPal capture webhooks don't include buyer email.
        # Merchants can pass it via custom_id when creating the order.
        custom_id = resource.get("custom_id") or ""
        email: str | None = custom_id if "@" in custom_id else None
        if not email:
            raise InvalidWebhookPayloadError(
                "PAYMENT.CAPTURE.COMPLETED: buyer email not available in capture. "
                "Set custom_id to the buyer email when creating the PayPal order."
            )

        amount_obj = resource.get("amount") or {}
        currency = (amount_obj.get("currency_code") or "USD").upper()
        try:
            amount_minor = int(float(amount_obj.get("value", 0)) * 100)
        except (TypeError, ValueError):
            amount_minor = 0

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type=canonical_type,
            occurred_at=occurred_at,
            customer=CanonicalCustomer(
                email=email,
                external_id=resource.get("id"),
                name=None,
            ),
            line_items=(
                CanonicalLineItem(
                    external_product_id=resource.get("id", event_id),
                    quantity=1,
                    amount_minor=amount_minor,
                    currency=currency,
                ),
            ),
            status="paid",
        )

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._supported_events

    @staticmethod
    def _parse_iso8601(value: str) -> datetime:
        parsed = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            dt = datetime.fromisoformat(parsed)
        except ValueError as exc:
            raise InvalidWebhookPayloadError("timestamp is not valid ISO8601") from exc
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

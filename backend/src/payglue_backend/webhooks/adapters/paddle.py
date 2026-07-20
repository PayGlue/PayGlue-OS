# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from datetime import UTC, datetime, timedelta
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

# Paddle's transaction events don't carry an email directly (only
# customer_id), so a transaction.completed event needs one extra API call
# to resolve the buyer's address. Subscription events do include a nested
# customer object with an email -- see Paddle's docs, not independently
# verified against a real event as of this writing.
_EVENT_MAP = {
    "transaction.completed": "order.paid",
    "subscription.activated": "subscription.active",
    "subscription.resumed": "subscription.active",
    "subscription.canceled": "subscription.canceled",
    "subscription.paused": "subscription.canceled",
    "subscription.past_due": "subscription.canceled",
}

_SIGNATURE_TOLERANCE_SECONDS = 5


class PaddlePaymentAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider,
        provider_key: str = "paddle",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._raw_event_names = set(_EVENT_MAP.keys())
        self._supported_events = set(_EVENT_MAP.values())

    def _base_url(self, sandbox: bool) -> str:
        return "https://sandbox-api.paddle.com" if sandbox else "https://api.paddle.com"

    def health_check(self, tenant_ctx: TenantContext) -> dict[str, object]:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        api_key = credentials.get("api_key")
        if not api_key:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("api_key",),
            )
        sandbox = credentials.get("sandbox", "") in ("true", "1", True)

        req = urllib.request.Request(
            f"{self._base_url(sandbox)}/products?per_page=1",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            # Report the real failure instead of masking it as missing
            # credentials -- credentials being present but rejected (wrong
            # key, wrong mode) is a different, more actionable message.
            return {"ok": False, "code": "api_error", "message": f"Paddle API error: HTTP {exc.code}."}
        except Exception as exc:
            return {"ok": False, "code": "api_error", "message": f"Paddle API call failed: {exc}"}

        return {
            "ok": True,
            "code": "ok",
            "message": "Paddle API key verified successfully.",
        }

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> None:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        webhook_secret = credentials.get("webhook_secret")
        if not webhook_secret:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("webhook_secret",),
            )

        signature_header = None
        for key, value in headers.items():
            if key.lower() == "paddle-signature":
                signature_header = value
                break

        # Confirmed against a real live purchase (2026-07-03): Paddle does
        # not sign notification deliveries here despite its docs describing
        # the Paddle-Signature header. Verify it if Paddle ever sends one,
        # but don't require it -- same situation as Gumroad's adapter.
        if signature_header is None:
            return

        parts: dict[str, str] = {}
        for chunk in signature_header.split(";"):
            if "=" not in chunk:
                continue
            k, _, v = chunk.partition("=")
            parts[k.strip()] = v.strip()

        timestamp = parts.get("ts")
        signature = parts.get("h1")
        if not timestamp or not signature:
            raise InvalidWebhookSignatureError("malformed Paddle-Signature header")

        try:
            event_time = datetime.fromtimestamp(int(timestamp), tz=UTC)
        except (TypeError, ValueError) as exc:
            raise InvalidWebhookSignatureError("invalid timestamp in Paddle-Signature") from exc

        if abs((self._now() - event_time).total_seconds()) > _SIGNATURE_TOLERANCE_SECONDS + 60:
            # A generous tolerance beyond Paddle's own 5s recommendation --
            # queued/retried webhooks can arrive later than that in practice.
            raise InvalidWebhookSignatureError("Paddle-Signature timestamp outside tolerance")

        signed_payload = f"{timestamp}:".encode() + raw_body
        expected = hmac.new(
            webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            raise InvalidWebhookSignatureError("signature mismatch")

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
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
        data = payload.get("data")
        if not isinstance(data, dict):
            raise InvalidWebhookPayloadError("missing data object")

        event_id = str(payload.get("event_id") or data.get("id") or "")
        if not event_id:
            raise InvalidWebhookPayloadError("missing event id")

        occurred_at = self._now()
        raw_time = payload.get("occurred_at")
        if isinstance(raw_time, str) and raw_time:
            try:
                occurred_at = self._parse_iso8601(raw_time)
            except InvalidWebhookPayloadError:
                pass

        if event_type == "transaction.completed":
            return self._parse_transaction(data, event_id, canonical_type, occurred_at, tenant_ctx)
        return self._parse_subscription(data, event_id, canonical_type, occurred_at)

    def _resolve_customer_email(
        self, customer_id: str, tenant_ctx: TenantContext
    ) -> str:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        api_key = credentials.get("api_key")
        if not api_key:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("api_key",),
            )
        sandbox = credentials.get("sandbox", "") in ("true", "1", True)

        req = urllib.request.Request(
            f"{self._base_url(sandbox)}/customers/{customer_id}",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
        except Exception as exc:
            raise InvalidWebhookPayloadError(
                f"could not resolve customer {customer_id}: {exc}"
            ) from exc

        email = (body.get("data") or {}).get("email")
        if not email:
            raise InvalidWebhookPayloadError(f"customer {customer_id} has no email on file")
        return email

    def _parse_transaction(
        self,
        data: dict,
        event_id: str,
        canonical_type: str,
        occurred_at: datetime,
        tenant_ctx: TenantContext,
    ) -> CanonicalPaymentEvent:
        customer_id = data.get("customer_id")
        if not customer_id:
            raise InvalidWebhookPayloadError("missing customer_id")
        email = self._resolve_customer_email(customer_id, tenant_ctx)

        items = data.get("items") or []
        if not items:
            raise InvalidWebhookPayloadError("missing items in transaction")
        first_item = items[0]
        price = first_item.get("price") or {}
        product_id = price.get("product_id") or price.get("id") or event_id

        totals = (data.get("details") or {}).get("totals") or {}
        currency = (data.get("currency_code") or totals.get("currency_code") or "USD").upper()
        try:
            amount_minor = int(totals.get("total", 0))
        except (TypeError, ValueError):
            amount_minor = 0

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type=canonical_type,
            occurred_at=occurred_at,
            customer=CanonicalCustomer(email=email, external_id=customer_id),
            line_items=(
                CanonicalLineItem(
                    external_product_id=str(product_id),
                    quantity=int(first_item.get("quantity", 1) or 1),
                    amount_minor=amount_minor,
                    currency=currency,
                ),
            ),
            status="paid",
        )

    def _parse_subscription(
        self, data: dict, event_id: str, canonical_type: str, occurred_at: datetime
    ) -> CanonicalPaymentEvent:
        customer = data.get("customer") or {}
        email = customer.get("email")
        if not email:
            raise InvalidWebhookPayloadError("missing customer.email in subscription event")

        items = data.get("items") or []
        product_id = event_id
        if items:
            price = items[0].get("price") or {}
            product_id = price.get("product_id") or price.get("id") or event_id

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type=canonical_type,
            occurred_at=occurred_at,
            customer=CanonicalCustomer(email=email, external_id=data.get("customer_id")),
            line_items=(
                CanonicalLineItem(
                    external_product_id=str(product_id),
                    quantity=1,
                    amount_minor=0,
                    currency=(data.get("currency_code") or "USD").upper(),
                ),
            ),
            status=data.get("status", "active"),
        )

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._supported_events

    def supports_raw_event_type(self, raw_event_type: str) -> bool:
        return raw_event_type in self._raw_event_names

    @staticmethod
    def _parse_iso8601(value: str) -> datetime:
        parsed = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            dt = datetime.fromisoformat(parsed)
        except ValueError as exc:
            raise InvalidWebhookPayloadError("timestamp is not valid ISO8601") from exc
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

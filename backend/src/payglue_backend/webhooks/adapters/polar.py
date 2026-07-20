# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from datetime import UTC, datetime
import base64
import hashlib
import hmac
import json
from typing import Callable, Protocol
from typing import Mapping

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


class PolarHealthClient(Protocol):
    def check_health(
        self, credentials: dict[str, str], tenant_ctx: TenantContext
    ) -> Mapping[str, object]: ...


class LocalPolarHealthClient:
    def check_health(
        self, credentials: dict[str, str], tenant_ctx: TenantContext
    ) -> Mapping[str, object]:
        del credentials, tenant_ctx
        return {
            "ok": True,
            "code": "ok",
            "message": "Polar credentials are configured.",
        }


class PolarPaymentAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider,
        provider_key: str = "polar",
        timestamp_tolerance_seconds: int = 300,
        now: Callable[[], datetime] | None = None,
        health_client: PolarHealthClient | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._timestamp_tolerance_seconds = timestamp_tolerance_seconds
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._health_client = health_client or LocalPolarHealthClient()
        self._supported_events = {"order.created", "order.paid", "subscription.active", "subscription.canceled", "subscription.revoked"}

    def health_check(self, tenant_ctx: TenantContext) -> dict[str, object]:
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

        try:
            raw_result = self._health_client.check_health(
                credentials=dict(credentials),
                tenant_ctx=tenant_ctx,
            )
        except Exception:
            return {
                "ok": False,
                "code": "transport_error",
                "message": "Polar health check failed.",
            }

        return {
            "ok": bool(raw_result.get("ok")),
            "code": str(raw_result.get("code", "unknown")),
            "message": str(raw_result.get("message", "")),
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

        if self._has_standard_webhook_headers(headers):
            self._verify_standard_webhook(
                raw_body=raw_body,
                headers=headers,
                webhook_secret=webhook_secret,
            )
            return

        signature_header = self._extract_signature_header(headers)
        parts = self._parse_signature_header(signature_header)
        timestamp = self._parse_timestamp(parts)

        now_ts = int(self._now().timestamp())
        if abs(now_ts - timestamp) > self._timestamp_tolerance_seconds:
            raise InvalidWebhookSignatureError("signature timestamp is stale")

        expected_signature = self._compute_signature(
            webhook_secret, timestamp, raw_body
        )
        provided_signature = parts.get("v1")
        if not isinstance(provided_signature, str) or not hmac.compare_digest(
            provided_signature, expected_signature
        ):
            raise InvalidWebhookSignatureError("signature mismatch")

    def _verify_standard_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        webhook_secret: str,
    ) -> None:
        webhook_id = self._require_header(headers, "webhook-id")
        webhook_timestamp = self._require_header(headers, "webhook-timestamp")
        webhook_signature = self._require_header(headers, "webhook-signature")

        timestamp = self._parse_int_timestamp(webhook_timestamp)
        now_ts = int(self._now().timestamp())
        if abs(now_ts - timestamp) > self._timestamp_tolerance_seconds:
            raise InvalidWebhookSignatureError("signature timestamp is stale")

        secret = self._decode_standard_secret(webhook_secret)
        signed_payload = f"{webhook_id}.{webhook_timestamp}.".encode("utf-8") + raw_body
        expected_signature = base64.b64encode(
            hmac.new(secret, signed_payload, hashlib.sha256).digest()
        ).decode("ascii")

        provided_signatures = self._parse_standard_signatures(webhook_signature)
        if not any(
            hmac.compare_digest(signature, expected_signature)
            for signature in provided_signatures
        ):
            raise InvalidWebhookSignatureError("signature mismatch")

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> CanonicalPaymentEvent:
        payload = self._parse_payload(raw_body)

        # Check event type before requiring id — unsupported events (e.g. checkout.updated)
        # may not have a top-level id field and should be gracefully skipped.
        event_type = self._require_str(payload, "type")
        if event_type not in self._supported_events:
            raise UnsupportedEventTypeError(event_type)

        # Polar standard webhook format: event ID is in webhook-id header, not payload body.
        raw_event_id = payload.get("id")
        if isinstance(raw_event_id, str) and raw_event_id:
            event_id = raw_event_id
        else:
            header_id = next(
                (v for k, v in headers.items() if k.lower() == "webhook-id"), None
            )
            if not header_id:
                raise InvalidWebhookPayloadError("field 'id' is required")
            event_id = header_id
        timestamp = self._parse_iso8601(self._require_str(payload, "timestamp"))

        data = payload.get("data")
        if not isinstance(data, dict):
            raise InvalidWebhookPayloadError("missing data object")

        if event_type == "subscription.canceled":
            return self._parse_subscription_event(
                data=data,
                event_id=event_id,
                event_type=event_type,
                timestamp=timestamp,
            )

        # Normalize order.created → order.paid so mappings stored as "order.paid" match.
        normalized_type = "order.paid" if event_type in ("order.created", "order.paid") else event_type
        return self._parse_order_event(
            data=data,
            event_id=event_id,
            event_type=normalized_type,
            timestamp=timestamp,
        )

    def _parse_order_event(
        self,
        data: dict[str, object],
        event_id: str,
        event_type: str,
        timestamp: "datetime",
    ) -> CanonicalPaymentEvent:
        # Polar order.paid: data IS the order — no nested data.order wrapper.
        customer = data.get("customer")
        if not isinstance(customer, dict):
            raise InvalidWebhookPayloadError("missing data.customer object")

        # Product ID from data.product.id (canonical product, not price)
        product_id: str | None = None
        product = data.get("product")
        if isinstance(product, dict):
            product_id = self._optional_str(product.get("id"))

        # Items are at data.items (price line items, not order.line_items)
        items_raw = data.get("items")
        if not isinstance(items_raw, list) or not items_raw:
            raise InvalidWebhookPayloadError("missing data.items array")

        currency = "USD"
        raw_currency = data.get("currency")
        if isinstance(raw_currency, str) and raw_currency:
            currency = raw_currency.upper()

        line_items: list[CanonicalLineItem] = []
        for item in items_raw:
            if not isinstance(item, dict):
                raise InvalidWebhookPayloadError("line item must be an object")
            # Use product_id from data.product; fall back to item.id (price ID)
            item_product_id = product_id or self._optional_str(item.get("product_id")) or self._optional_str(item.get("id"))
            if not item_product_id:
                raise InvalidWebhookPayloadError("cannot resolve product_id from order item")
            raw_amount = item.get("amount")
            amount = raw_amount if isinstance(raw_amount, int) else 0
            line_items.append(
                CanonicalLineItem(
                    external_product_id=item_product_id,
                    quantity=1,
                    amount_minor=amount,
                    currency=currency,
                )
            )

        status = self._optional_str(data.get("status")) or "paid"

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type=event_type,
            occurred_at=timestamp,
            customer=CanonicalCustomer(
                email=self._optional_str(customer.get("email")),
                external_id=self._optional_str(customer.get("id")),
                name=self._optional_str(customer.get("name")),
            ),
            line_items=tuple(line_items),
            status=status,
        )

    def _parse_subscription_event(
        self,
        data: dict[str, object],
        event_id: str,
        event_type: str,
        timestamp: "datetime",
    ) -> CanonicalPaymentEvent:
        subscription = data.get("subscription")
        if not isinstance(subscription, dict):
            raise InvalidWebhookPayloadError("missing data.subscription object")

        customer = subscription.get("customer")
        if not isinstance(customer, dict):
            raise InvalidWebhookPayloadError("missing subscription.customer object")

        # Extract product_id from subscription.product.id or subscription.price.product_id
        product_id: str | None = None
        product = subscription.get("product")
        if isinstance(product, dict):
            product_id = self._optional_str(product.get("id"))
        if not product_id:
            price = subscription.get("price")
            if isinstance(price, dict):
                product_id = self._optional_str(price.get("product_id"))
        if not product_id:
            raise InvalidWebhookPayloadError("cannot resolve product_id from subscription")

        price_amount = 0
        price_currency = "USD"
        price = subscription.get("price")
        if isinstance(price, dict):
            raw_amount = price.get("price_amount") or price.get("amount")
            if isinstance(raw_amount, int):
                price_amount = raw_amount
            raw_currency = price.get("price_currency") or price.get("currency")
            if isinstance(raw_currency, str):
                price_currency = raw_currency.upper()

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type=event_type,
            occurred_at=timestamp,
            customer=CanonicalCustomer(
                email=self._optional_str(customer.get("email")),
                external_id=self._optional_str(customer.get("id")),
                name=self._optional_str(customer.get("name")),
            ),
            line_items=(
                CanonicalLineItem(
                    external_product_id=product_id,
                    quantity=1,
                    amount_minor=price_amount,
                    currency=price_currency,
                ),
            ),
            status=self._optional_str(subscription.get("status")) or "canceled",
        )

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._supported_events

    def supports_raw_event_type(self, raw_event_type: str) -> bool:
        # Polar's raw webhook `type` field already uses the same names as
        # our canonical event types (order.created, order.paid, etc.).
        return raw_event_type in self._supported_events

    @staticmethod
    def _extract_signature_header(headers: Mapping[str, str]) -> str:
        for key, value in headers.items():
            if key.lower() == "polar-signature":
                return value
        raise InvalidWebhookSignatureError("missing Polar-Signature header")

    @staticmethod
    def _parse_signature_header(header_value: str) -> dict[str, str]:
        parts: dict[str, str] = {}
        for part in header_value.split(","):
            key, sep, value = part.partition("=")
            if not sep or not key or not value:
                continue
            parts[key.strip()] = value.strip()

        if "t" not in parts or "v1" not in parts:
            raise InvalidWebhookSignatureError("invalid signature header format")

        return parts

    @staticmethod
    def _parse_timestamp(signature_parts: Mapping[str, str]) -> int:
        raw_timestamp = signature_parts.get("t")
        if not isinstance(raw_timestamp, str):
            raise InvalidWebhookSignatureError("signature timestamp missing")
        return PolarPaymentAdapter._parse_int_timestamp(raw_timestamp)

    @staticmethod
    def _parse_int_timestamp(raw_timestamp: str) -> int:
        try:
            return int(raw_timestamp)
        except ValueError as exc:
            raise InvalidWebhookSignatureError(
                "signature timestamp is not an integer"
            ) from exc

    @staticmethod
    def _has_standard_webhook_headers(headers: Mapping[str, str]) -> bool:
        required = {"webhook-id", "webhook-timestamp", "webhook-signature"}
        normalized = {key.lower() for key in headers}
        return required.issubset(normalized)

    @staticmethod
    def _require_header(headers: Mapping[str, str], header_name: str) -> str:
        for key, value in headers.items():
            if key.lower() == header_name:
                return value
        raise InvalidWebhookSignatureError(f"missing {header_name} header")

    @staticmethod
    def _decode_standard_secret(webhook_secret: str) -> bytes:
        encoded = webhook_secret
        if encoded.startswith("whsec_"):
            encoded = encoded.removeprefix("whsec_")
        try:
            return base64.b64decode(encoded, validate=True)
        except Exception:
            return webhook_secret.encode("utf-8")

    @staticmethod
    def _parse_standard_signatures(signature_header: str) -> list[str]:
        parsed: list[str] = []
        for part in signature_header.split(" "):
            version, sep, signature = part.partition(",")
            if sep and version == "v1" and signature:
                parsed.append(signature)

        if not parsed:
            raise InvalidWebhookSignatureError("invalid standard signature format")
        return parsed

    @staticmethod
    def _compute_signature(secret: str, timestamp: int, raw_body: bytes) -> str:
        payload = str(timestamp).encode("utf-8") + b"." + raw_body
        return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _parse_payload(raw_body: bytes) -> dict[str, object]:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise InvalidWebhookPayloadError("payload is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise InvalidWebhookPayloadError("payload must be a JSON object")
        return payload

    @staticmethod
    def _require_str(payload: dict[str, object], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise InvalidWebhookPayloadError(f"field '{field}' is required")
        return value

    @staticmethod
    def _optional_str(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value
        return None

    @staticmethod
    def _require_int(payload: dict[str, object], field: str) -> int:
        value = payload.get(field)
        if not isinstance(value, int):
            raise InvalidWebhookPayloadError(f"field '{field}' must be an integer")
        return value

    @staticmethod
    def _parse_iso8601(value: str) -> datetime:
        parsed = value
        if parsed.endswith("Z"):
            parsed = parsed[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(parsed)
        except ValueError as exc:
            raise InvalidWebhookPayloadError("timestamp is not valid ISO8601") from exc

        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

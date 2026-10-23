# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""
Dodo Payments adapter for tenant-connected Ghost blogs.

Dodo is a merchant of record. Its webhooks follow the Standard Webhooks
specification: the signature covers `webhook-id`, `webhook-timestamp` and the
raw body, the secret is `whsec_` plus the base64 key, and every delivery
carries a unique `webhook-id`, which is the event id here.

Event names and payload fields come from Dodo's documentation and official
SDK (`dodopayments-python`, types `Payment` and `Subscription`). They are not
yet confirmed against a real delivery. Until a test-mode purchase, renewal,
cancellation and expiry have gone through and are kept as fixtures, treat the
mapping below as provisional, the same caveat the Creem and Paddle adapters
carried before theirs were confirmed.

Mapping:
- payment.succeeded without a subscription: a one-time purchase, order.paid.
  With a subscription it is a first payment or a renewal; the subscription
  events carry that, so the payment is skipped.
- subscription.active, subscription.renewed: access.
- subscription.cancelled: keeps access until next_billing_date when the
  cancellation is booked for the end of the period; ends it otherwise.
- subscription.expired: ends access.
- Everything else (past_due, on_hold, paused, plan_changed, ...) is skipped:
  Dodo keeps or ends the subscription later and says so with one of the
  events above.
"""
import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from dataclasses import replace
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

TEST_BASE = "https://test.dodopayments.com"
LIVE_BASE = "https://live.dodopayments.com"

_HANDLED = {
    "payment.succeeded": "order.paid",
    "subscription.active": "subscription.active",
    "subscription.renewed": "subscription.active",
    "subscription.cancelled": "subscription.revoked",
    "subscription.expired": "subscription.revoked",
}

# Which base a key belongs to. A key works against exactly one of them, and
# that does not change for the life of the key.
_KEY_MODE: dict[str, str] = {}


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def dodo_get(path: str, api_key: str, base: str) -> dict:
    req = urllib.request.Request(
        f"{base}{path}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "PayGlue/1.0 (https://payglue.io)",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def dodo_key_mode(api_key: str) -> str:
    """"test" or "live", whichever base accepts the key.

    Dodo keys are bound to one environment and the key itself does not say
    which. Trying both is what the Creem adapter does for the same reason.
    """
    fingerprint = _key_fingerprint(api_key)
    if fingerprint in _KEY_MODE:
        return _KEY_MODE[fingerprint]
    last_exc: Exception | None = None
    for mode, base in (("test", TEST_BASE), ("live", LIVE_BASE)):
        try:
            dodo_get("/products?page_size=1", api_key, base)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                last_exc = exc
                continue
            raise
        _KEY_MODE[fingerprint] = mode
        return mode
    raise last_exc or urllib.error.URLError("Dodo API request failed in both environments.")


def dodo_base(api_key: str) -> str:
    return TEST_BASE if dodo_key_mode(api_key) == "test" else LIVE_BASE


class DodoPaymentAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider,
        provider_key: str = "dodo",
        now: Callable[[], datetime] | None = None,
        timestamp_tolerance_seconds: int = 300,
    ) -> None:
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._timestamp_tolerance_seconds = timestamp_tolerance_seconds
        self._raw_event_names = set(_HANDLED)
        self._supported_events = set(_HANDLED.values())

    def _credentials(self, tenant_ctx: TenantContext) -> Mapping[str, str]:
        return self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )

    def health_check(self, tenant_ctx: TenantContext) -> dict[str, object]:
        api_key = self._credentials(tenant_ctx).get("api_key")
        if not api_key:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("api_key",),
            )
        try:
            mode = dodo_key_mode(api_key)
        except urllib.error.HTTPError as exc:
            return {"ok": False, "code": "api_error", "message": f"Dodo API error: HTTP {exc.code}."}
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return {"ok": False, "code": "api_error", "message": f"Dodo API call failed: {exc}"}
        label = "test mode" if mode == "test" else "live mode"
        return {"ok": True, "code": "ok", "message": f"Dodo API key verified ({label})."}

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> None:
        webhook_secret = self._credentials(tenant_ctx).get("webhook_secret")
        if not webhook_secret:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("webhook_secret",),
            )

        webhook_id = self._require_header(headers, "webhook-id")
        webhook_timestamp = self._require_header(headers, "webhook-timestamp")
        webhook_signature = self._require_header(headers, "webhook-signature")

        try:
            timestamp = int(webhook_timestamp)
        except ValueError as exc:
            raise InvalidWebhookSignatureError("signature timestamp is not an integer") from exc
        if abs(int(self._now().timestamp()) - timestamp) > self._timestamp_tolerance_seconds:
            raise InvalidWebhookSignatureError("signature timestamp is stale")

        try:
            key = base64.b64decode(webhook_secret.removeprefix("whsec_"), validate=True)
        except Exception as exc:
            raise InvalidWebhookSignatureError("webhook secret is not a Standard Webhooks secret") from exc

        signed = f"{webhook_id}.{webhook_timestamp}.".encode("utf-8") + raw_body
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")
        provided = [
            sig
            for version, _, sig in (part.partition(",") for part in webhook_signature.split(" "))
            if version == "v1" and sig
        ]
        if not provided:
            raise InvalidWebhookSignatureError("invalid standard signature format")
        if not any(hmac.compare_digest(sig, expected) for sig in provided):
            raise InvalidWebhookSignatureError("signature mismatch")

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> CanonicalPaymentEvent:
        event = self._parse_event_untagged(raw_body, headers)
        try:
            api_key = self._credentials(tenant_ctx).get("api_key")
            is_test = bool(api_key) and dodo_key_mode(api_key) == "test"
        except Exception:  # noqa: BLE001 - a broken test-mode probe must not fail the payment
            is_test = False
        return replace(event, is_test=is_test)

    def _parse_event_untagged(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> CanonicalPaymentEvent:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise InvalidWebhookPayloadError("payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise InvalidWebhookPayloadError("payload must be a JSON object")

        raw_type = payload.get("type")
        if not isinstance(raw_type, str) or raw_type not in self._raw_event_names:
            raise UnsupportedEventTypeError(str(raw_type))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise InvalidWebhookPayloadError("missing data object")

        occurred_at = self._parse_time(payload.get("timestamp")) or self._now()
        event_id = self._header(headers, "webhook-id") or self._fallback_id(raw_type, data, occurred_at)

        if raw_type == "payment.succeeded":
            return self._payment_event(data, event_id, occurred_at)
        return self._subscription_event(raw_type, data, event_id, occurred_at)

    def _payment_event(
        self, data: dict, event_id: str, occurred_at: datetime
    ) -> CanonicalPaymentEvent:
        if data.get("subscription_ids") or data.get("subscription_id"):
            raise UnsupportedEventTypeError(
                "payment belongs to a subscription, the subscription events carry it"
            )
        cart = data.get("product_cart") if isinstance(data.get("product_cart"), list) else []
        product_ids = [str(i["product_id"]) for i in cart if isinstance(i, dict) and i.get("product_id")]
        if not product_ids and data.get("product_id"):
            product_ids = [str(data["product_id"])]
        if not product_ids:
            raise InvalidWebhookPayloadError("cannot resolve product_id from payment")
        currency = str(data.get("currency") or "USD").upper()
        amount = data.get("total_amount") if isinstance(data.get("total_amount"), int) else 0
        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type="order.paid",
            occurred_at=occurred_at,
            customer=self._customer(data),
            line_items=tuple(
                CanonicalLineItem(
                    external_product_id=pid,
                    quantity=1,
                    amount_minor=amount if len(product_ids) == 1 else 0,
                    currency=currency,
                )
                for pid in product_ids
            ),
            status="paid",
        )

    def _subscription_event(
        self, raw_type: str, data: dict, event_id: str, occurred_at: datetime
    ) -> CanonicalPaymentEvent:
        if raw_type == "subscription.cancelled" and data.get("cancel_at_next_billing_date"):
            # A cancellation booked for the end of the period keeps the paid
            # access; Dodo sends subscription.expired when it actually ends.
            # A missing or unreadable date counts as running: one cycle too
            # long is the smaller wrong. An immediate cancellation ends access
            # right away.
            ends = self._parse_time(data.get("next_billing_date"))
            if ends is None or ends > self._now():
                raise UnsupportedEventTypeError(
                    f"cancellation keeps access until {data.get('next_billing_date')}"
                )
        product_id = data.get("product_id")
        if not product_id:
            raise InvalidWebhookPayloadError("cannot resolve product_id from subscription")
        amount = data.get("recurring_pre_tax_amount") if isinstance(data.get("recurring_pre_tax_amount"), int) else 0
        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type=_HANDLED[raw_type],
            occurred_at=occurred_at,
            customer=self._customer(data),
            line_items=(
                CanonicalLineItem(
                    external_product_id=str(product_id),
                    quantity=1,
                    amount_minor=amount,
                    currency=str(data.get("currency") or "USD").upper(),
                ),
            ),
            status=str(data.get("status") or ("active" if _HANDLED[raw_type] == "subscription.active" else "expired")),
        )

    @staticmethod
    def _customer(data: dict) -> CanonicalCustomer:
        customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
        email = str(customer.get("email") or "").strip().lower()
        if not email:
            raise InvalidWebhookPayloadError("missing customer email")
        return CanonicalCustomer(
            email=email,
            external_id=str(customer.get("customer_id") or "") or None,
            name=str(customer.get("name") or "") or None,
        )

    @staticmethod
    def _fallback_id(raw_type: str, data: dict, occurred_at: datetime) -> str:
        ref = data.get("payment_id") or data.get("subscription_id")
        if not ref:
            raise InvalidWebhookPayloadError("missing event id")
        return f"{ref}:{raw_type}:{occurred_at.isoformat()}"

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str | None:
        for key, value in headers.items():
            if key.lower() == name:
                return value
        return None

    @classmethod
    def _require_header(cls, headers: Mapping[str, str], name: str) -> str:
        value = cls._header(headers, name)
        if not value:
            raise InvalidWebhookSignatureError(f"missing {name} header")
        return value

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._supported_events

    def supports_raw_event_type(self, raw_event_type: str) -> bool:
        return raw_event_type in self._raw_event_names

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from datetime import UTC, datetime
import hashlib
import hmac
import json
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

_EVENT_MAP = {
    "order_created": "order.paid",
    "subscription_created": "subscription.active",
    "subscription_updated": "subscription.active",
    "subscription_resumed": "subscription.active",
    "subscription_unpaused": "subscription.active",
    "subscription_cancelled": "subscription.canceled",
    "subscription_paused": "subscription.canceled",
    "subscription_expired": "subscription.revoked",
}
# subscription_payment_success is not in the map. Its data is a subscription
# invoice, which names no variant, so it could never be matched to a rule and
# failed as an invalid payload. The subscription events carry the state that
# matters; a renewal arrives as subscription_updated with status active.

# What a subscription_updated means depends on the status it reports
# (PG-337). Lemon Squeezy sends it next to nearly every other
# subscription event, including the cancellation and the expiry.
_ACTIVE_STATUSES = frozenset({"active", "on_trial"})


class LemonSqueezyPaymentAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider,
        provider_key: str = "lemonsqueezy",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._raw_event_names = set(_EVENT_MAP.keys())
        self._supported_events = set(_EVENT_MAP.values())

    def health_check(self, tenant_ctx: TenantContext) -> dict[str, object]:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        if not credentials.get("webhook_secret"):
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("webhook_secret",),
            )
        return {
            "ok": True,
            "code": "ok",
            "message": "Lemon Squeezy credentials are configured.",
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

        signature = None
        for key, value in headers.items():
            if key.lower() == "x-signature":
                signature = value
                break

        if not signature:
            raise InvalidWebhookSignatureError("missing X-Signature header")

        expected = hmac.new(
            webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            raise InvalidWebhookSignatureError("signature mismatch")

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> CanonicalPaymentEvent:
        event = self._parse_event_untagged(raw_body, headers, tenant_ctx)
        try:
            is_test = self._is_test_event(raw_body, headers, tenant_ctx)
        except Exception:  # noqa: BLE001 - a broken test-mode probe must not fail the payment
            is_test = False
        return replace(event, is_test=is_test)

    @staticmethod
    def _is_test_event(raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext) -> bool:
        """Lemon Squeezy sends meta.test_mode on every webhook."""
        payload = json.loads(raw_body)
        meta = payload.get("meta") if isinstance(payload, dict) else None
        return isinstance(meta, dict) and meta.get("test_mode") is True

    def _parse_event_untagged(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> CanonicalPaymentEvent:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise InvalidWebhookPayloadError("payload is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise InvalidWebhookPayloadError("payload must be a JSON object")

        meta = payload.get("meta")
        if not isinstance(meta, dict):
            raise InvalidWebhookPayloadError("missing meta object")

        event_name = meta.get("event_name")
        if not isinstance(event_name, str) or not event_name:
            raise InvalidWebhookPayloadError("missing meta.event_name")

        if event_name not in self._raw_event_names:
            raise UnsupportedEventTypeError(event_name)

        canonical_type = _EVENT_MAP[event_name]

        data = payload.get("data")
        if not isinstance(data, dict):
            raise InvalidWebhookPayloadError("missing data object")

        event_id = str(data.get("id", ""))
        if not event_id:
            raise InvalidWebhookPayloadError("missing data.id")

        attrs = data.get("attributes")
        if not isinstance(attrs, dict):
            raise InvalidWebhookPayloadError("missing data.attributes")

        occurred_at = self._now()
        raw_created = attrs.get("created_at")
        if isinstance(raw_created, str) and raw_created:
            try:
                occurred_at = self._parse_iso8601(raw_created)
            except InvalidWebhookPayloadError:
                pass

        email = attrs.get("user_email") or attrs.get("user_name")
        customer_email = email if isinstance(email, str) and email else None
        customer_name_raw = attrs.get("user_name")
        customer_name = customer_name_raw if isinstance(customer_name_raw, str) else None
        customer_id_raw = attrs.get("customer_id")
        customer_id = str(customer_id_raw) if customer_id_raw is not None else None

        if event_name != "order_created":
            # PG-337: Lemon Squeezy sends no id of its own for a webhook, and
            # data.id is the subscription. Used alone as the event id, it made
            # every later event for the same subscription a duplicate of the
            # first one, so a cancellation or an expiry was dropped and the
            # reader kept access. The event name and the subscription's
            # updated_at tell the events apart, and a redelivery of the same
            # event still carries the same pair.
            updated_at = attrs.get("updated_at")
            event_id = f"{event_id}:{event_name}"
            if isinstance(updated_at, str) and updated_at:
                event_id = f"{event_id}:{updated_at}"
            canonical_type = self._subscription_outcome(event_name, attrs)

        if event_name == "order_created":
            return self._parse_order(
                attrs=attrs,
                event_id=event_id,
                canonical_type=canonical_type,
                occurred_at=occurred_at,
                customer_email=customer_email,
                customer_name=customer_name,
                customer_id=customer_id,
            )
        else:
            return self._parse_subscription(
                attrs=attrs,
                event_id=event_id,
                canonical_type=canonical_type,
                occurred_at=occurred_at,
                customer_email=customer_email,
                customer_name=customer_name,
                customer_id=customer_id,
            )

    def _parse_order(
        self,
        attrs: dict,
        event_id: str,
        canonical_type: str,
        occurred_at: datetime,
        customer_email: str | None,
        customer_name: str | None,
        customer_id: str | None,
    ) -> CanonicalPaymentEvent:
        first_item = attrs.get("first_order_item")
        if not isinstance(first_item, dict):
            raise InvalidWebhookPayloadError("missing first_order_item in order")

        variant_id = first_item.get("variant_id")
        product_id = str(variant_id) if variant_id is not None else None
        if not product_id:
            raise InvalidWebhookPayloadError("cannot resolve variant_id from order item")

        amount_raw = first_item.get("price")
        amount = amount_raw if isinstance(amount_raw, int) else 0
        currency_raw = attrs.get("currency")
        currency = currency_raw.upper() if isinstance(currency_raw, str) and currency_raw else "USD"
        status_raw = attrs.get("status")
        status = status_raw if isinstance(status_raw, str) and status_raw else "paid"

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type=canonical_type,
            occurred_at=occurred_at,
            customer=CanonicalCustomer(
                email=customer_email,
                external_id=customer_id,
                name=customer_name,
            ),
            line_items=(
                CanonicalLineItem(
                    external_product_id=product_id,
                    quantity=1,
                    amount_minor=amount,
                    currency=currency,
                ),
            ),
            status=status,
        )

    def _parse_subscription(
        self,
        attrs: dict,
        event_id: str,
        canonical_type: str,
        occurred_at: datetime,
        customer_email: str | None,
        customer_name: str | None,
        customer_id: str | None,
    ) -> CanonicalPaymentEvent:
        variant_id = attrs.get("variant_id")
        product_id = str(variant_id) if variant_id is not None else None
        if not product_id:
            raise InvalidWebhookPayloadError("cannot resolve variant_id from subscription")

        status_raw = attrs.get("status")
        status = status_raw if isinstance(status_raw, str) and status_raw else "active"

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type=canonical_type,
            occurred_at=occurred_at,
            customer=CanonicalCustomer(
                email=customer_email,
                external_id=customer_id,
                name=customer_name,
            ),
            line_items=(
                CanonicalLineItem(
                    external_product_id=product_id,
                    quantity=1,
                    amount_minor=0,
                    currency="USD",
                ),
            ),
            status=status,
        )

    def _subscription_outcome(self, event_name: str, attrs: dict) -> str:
        """The canonical event a subscription webhook stands for, or a skip.

        A skip is raised as UnsupportedEventTypeError, because doing nothing is
        the correct outcome, not an error to retry.
        """
        status = attrs.get("status")
        ends_at = attrs.get("ends_at")
        ends_at = ends_at if isinstance(ends_at, str) and ends_at else None

        if event_name == "subscription_cancelled" or (
            event_name == "subscription_updated" and status == "cancelled"
        ):
            # A cancellation runs to the end of the paid period. The reader
            # paid through ends_at and keeps access until then, and Lemon
            # Squeezy sends subscription_expired when it is over. Only a
            # cancellation whose period has already run out ends access here.
            if self._still_running(ends_at):
                raise UnsupportedEventTypeError(
                    "cancellation runs to the end of the paid period, "
                    f"access runs until {ends_at}"
                )
            return "subscription.revoked"

        if event_name == "subscription_paused":
            # A pause in "free" mode keeps the reader's access while billing
            # stops. Only a "void" pause takes it away.
            pause = attrs.get("pause")
            if isinstance(pause, dict) and pause.get("mode") == "free":
                raise UnsupportedEventTypeError("paused with free access, access stays")
            return "subscription.canceled"

        if event_name == "subscription_updated":
            if status in _ACTIVE_STATUSES:
                return "subscription.active"
            if status == "expired":
                return "subscription.revoked"
            # past_due and unpaid are payment retries, paused has its own
            # event. None of them changes access by itself; an expiry follows
            # if the retries fail.
            raise UnsupportedEventTypeError(f"subscription_updated with status {status!r}")

        return _EVENT_MAP[event_name]

    def _still_running(self, ends_at: str | None) -> bool:
        """True while the paid period has not run out. A missing or unreadable
        date counts as running: keeping access until the expiry event is the
        safe side, taking it early is not."""
        if not ends_at:
            return True
        try:
            return self._parse_iso8601(ends_at) > self._now()
        except InvalidWebhookPayloadError:
            return True

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._supported_events

    def supports_raw_event_type(self, raw_event_type: str) -> bool:
        return raw_event_type in self._raw_event_names

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

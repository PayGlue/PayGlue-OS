# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import parse_qsl
import json
import secrets
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

# Ko-fi has no dashboard concept of distinct products/tiers you can fetch via
# API, and every payment type it fires a webhook for (Donation/Tip,
# Subscription, Shop Order, Commission) represents money actually received --
# so all of them map to the single canonical "order.paid" event, same
# treatment Polar gives its various one-time/renewal events. Unlike every
# other provider here, Ko-fi never sends a membership-ended webhook at all
# (confirmed against their docs, not just an unsigned-payload situation like
# Gumroad/Paddle) -- there is deliberately no subscription.canceled mapping
# below.
#
# Both "Tip" (current docs) and "Donation" (Ko-fi's own dashboard "Send Test"
# button still sends this legacy name) are accepted -- confirmed 2026-07-07
# when a real test webhook from Ko-fi's dashboard came back "Donation" and
# was silently dropped because only "Tip" was allowlisted.
_SUPPORTED_RAW_TYPES = {"Tip", "Donation", "Subscription", "Shop Order", "Commission"}


class KofiPaymentAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider,
        provider_key: str = "kofi",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._now = now or (lambda: datetime.now(tz=UTC))

    def health_check(self, tenant_ctx: TenantContext) -> dict[str, object]:
        # Ko-fi has no API to call for a real connectivity check -- the
        # verification token is only ever exercised passively, when Ko-fi
        # itself sends a webhook. Confirm it's at least configured.
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        if not credentials.get("verification_token"):
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("verification_token",),
            )
        return {
            "ok": True,
            "code": "ok",
            "message": "Ko-fi verification token is configured. Trigger a test webhook from Ko-fi to confirm delivery.",
        }

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> None:
        credentials = self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )
        expected_token = credentials.get("verification_token")
        if not expected_token:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("verification_token",),
            )

        data = self._decode_data(raw_body)
        actual_token = data.get("verification_token")
        if not isinstance(actual_token, str) or not secrets.compare_digest(
            actual_token, expected_token
        ):
            raise InvalidWebhookSignatureError("verification token mismatch")

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> CanonicalPaymentEvent:
        data = self._decode_data(raw_body)

        raw_type = data.get("type")
        if not isinstance(raw_type, str) or raw_type not in _SUPPORTED_RAW_TYPES:
            raise UnsupportedEventTypeError(f"unsupported ko-fi type '{raw_type}'")

        email = data.get("email")
        if not email:
            raise InvalidWebhookPayloadError("missing email")

        message_id = data.get("kofi_transaction_id") or data.get("message_id")
        if not message_id:
            raise InvalidWebhookPayloadError("missing transaction id")

        currency = str(data.get("currency") or "USD").upper()
        try:
            amount_minor = round(float(data.get("amount", 0) or 0) * 100)
        except (TypeError, ValueError):
            amount_minor = 0

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=str(message_id),
            event_type="order.paid",
            occurred_at=self._parse_timestamp(data.get("timestamp")),
            customer=CanonicalCustomer(email=str(email), external_id=data.get("from_name")),
            line_items=self._build_line_items(data, amount_minor, currency),
            status="paid",
        )

    @staticmethod
    def _build_line_items(
        data: dict, amount_minor: int, currency: str
    ) -> tuple[CanonicalLineItem, ...]:
        # Shop Order payloads carry no product name at all -- Ko-fi's own docs
        # example shows `shop_items: [{"direct_link_code": "..."}]` with
        # tier_name null, so direct_link_code (the id in the item's Ko-fi
        # share URL, e.g. the "c0e3..." in https://ko-fi.com/s/c0e3...) is the
        # only usable product identifier for a shop purchase. A cart can hold
        # several items; the pipeline (resolver.py/orchestrator.py) already
        # resolves + grants one entitlement per distinct external_product_id
        # across all line items, same as Polar's multi-item orders, so one
        # line item per shop_items entry is correctly handled downstream.
        # Ko-fi gives no per-item price, so the full order amount is repeated
        # on each line item rather than split -- informational only, it does
        # not affect which entitlements get granted.
        shop_items = data.get("shop_items")
        if isinstance(shop_items, list) and shop_items:
            codes = [
                item.get("direct_link_code")
                for item in shop_items
                if isinstance(item, dict) and item.get("direct_link_code")
            ]
            if codes:
                counts = Counter(codes)
                return tuple(
                    CanonicalLineItem(
                        external_product_id=str(code),
                        quantity=qty,
                        amount_minor=amount_minor,
                        currency=currency,
                    )
                    for code, qty in counts.items()
                )

        # Subscription payloads carry tier_name; plain tips carry neither --
        # fall back to a shared bucket product id, there is nothing more
        # specific to key a ProductMapping on for a one-off tip.
        product_ref = data.get("tier_name") or "kofi-support"
        return (
            CanonicalLineItem(
                external_product_id=str(product_ref),
                quantity=1,
                amount_minor=amount_minor,
                currency=currency,
            ),
        )

    def supports_event(self, event_type: str) -> bool:
        return event_type == "order.paid"

    def supports_raw_event_type(self, raw_event_type: str) -> bool:
        return raw_event_type in _SUPPORTED_RAW_TYPES

    @staticmethod
    def _decode_data(raw_body: bytes) -> dict:
        try:
            pairs = parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError as exc:
            raise InvalidWebhookPayloadError("payload is not valid form data") from exc
        payload = dict(pairs)
        raw_data = payload.get("data")
        if not raw_data:
            raise InvalidWebhookPayloadError("missing 'data' field")
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError as exc:
            raise InvalidWebhookPayloadError("'data' field is not valid JSON") from exc
        if not isinstance(data, dict):
            raise InvalidWebhookPayloadError("'data' field must be a JSON object")
        return data

    def _parse_timestamp(self, value: object) -> datetime:
        if isinstance(value, str) and value:
            try:
                parsed = value[:-1] + "+00:00" if value.endswith("Z") else value
                dt = datetime.fromisoformat(parsed)
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
            except ValueError:
                pass
        return self._now()

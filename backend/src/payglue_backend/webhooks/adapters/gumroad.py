# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from datetime import UTC, datetime
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse
import hashlib
import hmac
import json
from dataclasses import replace
import urllib.error
import urllib.request
from typing import Callable, Mapping

from payglue_backend.core.errors import (
    AccessRunsUntilError,
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
    # Gumroad creates a subscription with PUT. Every save first removes the
    # subscriptions this installation registered for the tenant under an
    # older address (for example one without the key), so they do not keep
    # failing next to the current one, and skips a resource that already
    # points at the current address.
    _WEBHOOK_RESOURCE_NAMES = ("sale", "cancellation", "subscription_ended")
    _API_BASE = "https://api.gumroad.com/v2"

    def _call(self, method: str, path: str, params: dict[str, str]) -> dict:
        query = urlencode(params)
        if method in ("GET", "DELETE"):
            req = urllib.request.Request(f"{self._API_BASE}{path}?{query}", method=method)
        else:
            req = urllib.request.Request(
                f"{self._API_BASE}{path}", data=query.encode("utf-8"), method=method
            )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    @staticmethod
    def _is_own_address(post_url: str, webhook_url: str) -> bool:
        """Same path and tenant as the address we register now. The host is
        left out on purpose: an installation that registered under another
        origin of itself (an internal host before PUBLIC_API_BASE_URL was
        set) has to be able to clean that up."""
        current = urlparse(webhook_url)
        candidate = urlparse(post_url or "")
        return (
            candidate.path.rstrip("/") == current.path.rstrip("/")
            and parse_qs(candidate.query).get("tenant") == parse_qs(current.query).get("tenant")
        )

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
            try:
                existing = self._call(
                    "GET",
                    "/resource_subscriptions",
                    {"access_token": access_token, "resource_name": resource_name},
                ).get("resource_subscriptions") or []
                already_current = False
                for subscription in existing:
                    post_url = subscription.get("post_url", "")
                    if not self._is_own_address(post_url, webhook_url):
                        continue
                    if post_url == webhook_url and not already_current:
                        already_current = True
                        continue
                    self._call(
                        "DELETE",
                        f"/resource_subscriptions/{subscription['id']}",
                        {"access_token": access_token},
                    )
                if already_current:
                    registered.append(resource_name)
                    continue
                data = self._call(
                    "PUT",
                    "/resource_subscriptions",
                    {
                        "access_token": access_token,
                        "resource_name": resource_name,
                        "post_url": webhook_url,
                    },
                )
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
        event = self._parse_event_untagged(raw_body, headers, tenant_ctx)
        try:
            is_test = self._is_test_event(raw_body, headers, tenant_ctx)
        except Exception:  # noqa: BLE001 - a broken test-mode probe must not fail the payment
            is_test = False
        return replace(event, is_test=is_test)

    def _is_test_event(self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext) -> bool:
        """Gumroad marks sales made with the seller's test card, and its test
        pings, with a test flag."""
        payload = self._decode_payload(raw_body, headers)
        return str(payload.get("test", "")).lower() in ("true", "1")

    def _parse_event_untagged(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> CanonicalPaymentEvent:
        payload = self._decode_payload(raw_body, headers)

        # Sales carry `email`; the subscription lifecycle resources carry
        # `user_email` instead (seen on a real cancellation, 4 November 2026).
        email = payload.get("email") or payload.get("user_email")
        if not email:
            raise InvalidWebhookPayloadError("missing email")

        sale_id = payload.get("sale_id")
        subscription_id = payload.get("subscription_id")
        product_id = payload.get("product_id") or payload.get("permalink")
        resource_name = payload.get("resource_name")

        if sale_id:
            return self._parse_sale(payload, email, sale_id, product_id)
        if subscription_id and (
            resource_name == "cancellation" or self._is_truthy(payload.get("cancelled"))
        ):
            # A cancellation runs to the end of the paid period. Gumroad sends
            # it when the buyer cancels, with cancelled_at set to the day access
            # ends: a yearly plan bought on 3 November 2026 and cancelled the
            # next day came back with cancelled_at 3 November 2027.
            # subscription_ended follows on that day. Only a cancellation whose
            # date has already passed ends access here.
            cancelled_at = payload.get("cancelled_at")
            if self._still_running(cancelled_at):
                message = (
                    "cancellation runs to the end of the paid period, "
                    f"access runs until {cancelled_at}"
                )
                ends_at = self._end_date(cancelled_at)
                if ends_at is None:
                    raise UnsupportedEventTypeError(message)
                # subscription_ended has not been seen live yet, and
                # without it access would never end. The end is queued for
                # cancelled_at as a delivery of its own that looks like
                # subscription_ended, so it carries the same event id: whichever
                # arrives first ends access and the other is a duplicate.
                raise AccessRunsUntilError(
                    message, ends_at=ends_at, end_payload=self._scheduled_end(payload, cancelled_at)
                )
            return self._parse_lifecycle(
                payload, email, subscription_id, product_id, "subscription.revoked", "cancelled"
            )
        if subscription_id and (
            resource_name == "subscription_ended"
            or self._is_truthy(payload.get("ended"))
            or payload.get("ended_at")
        ):
            return self._parse_lifecycle(
                payload, email, subscription_id, product_id, "subscription.revoked", "ended"
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
        stage: str,
    ) -> CanonicalPaymentEvent:
        return CanonicalPaymentEvent(
            provider=self._provider_key,
            # One subscription sends a cancellation and later its end, both
            # with the same subscription_id. Keyed on the id alone, the end
            # was dropped as a duplicate of the cancellation (PG-339).
            provider_event_id=f"{subscription_id}:{stage}",
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

    def _end_date(self, value: object) -> datetime | None:
        """cancelled_at as an aware datetime, or None when it cannot be read."""
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _scheduled_end(payload: dict, ends_at: str) -> bytes:
        """The delivery that ends access on cancelled_at, form encoded like
        Gumroad's own pings because a queued event keeps no headers."""
        fields = {
            key: value
            for key, value in payload.items()
            if key not in ("cancelled", "cancelled_at")
        }
        fields.update(resource_name="subscription_ended", ended_at=ends_at)
        return urlencode(fields).encode("utf-8")

    def subscription_is_active(self, tenant_ctx: TenantContext, raw_body: bytes) -> bool:
        """Whether the subscription behind a queued end runs again, because
        the buyer restarted it after cancelling. Raises when Gumroad cannot be
        asked, so the end waits for the next night instead of guessing."""
        payload = self._decode_payload(raw_body, {})
        subscription_id = payload.get("subscription_id")
        if not subscription_id:
            return False
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
        data = self._call("GET", f"/subscribers/{subscription_id}", {"access_token": access_token})
        subscriber = data.get("subscriber") or {}
        return str(subscriber.get("status", "")).lower() == "alive"

    def _still_running(self, ends_at: object) -> bool:
        """True while the paid period has not run out. A missing or unreadable
        date counts as running: keeping access until subscription_ended is the
        safe side, taking it early is not."""
        if not isinstance(ends_at, str) or not ends_at:
            return True
        try:
            parsed = ends_at[:-1] + "+00:00" if ends_at.endswith("Z") else ends_at
            dt = datetime.fromisoformat(parsed)
        except ValueError:
            return True
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt > self._now()

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

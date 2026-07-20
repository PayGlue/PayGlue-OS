# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""
Creem.io adapter for tenant-connected Ghost blogs (GOGU-135).

Not to be confused with authn/creem_access.py + authn/creem_webhook.py,
which handle PayGlue's own Founding Member billing -- see the note on the
latter. Credentials here live in TenantProviderCredential like every other
provider, not in settings-level CREEM_API_KEY/CREEM_WEBHOOK_SECRET.

Event shape for checkout.completed is verified against the object PayGlue's
own billing webhook already parses (see creem_webhook.py, docs.creem.io).
Subscription-lifecycle event names/payloads are NOT yet verified against a
real Creem delivery -- GOGU-135 itself flags this as "verify against real
webhook payloads at implementation time". Treat _EVENT_MAP's subscription
entries as a best-effort mapping from Creem's public docs until a real
sandbox event confirms them, same caveat Paddle's adapter carries for its
own unverified fields.
"""
from datetime import UTC, datetime
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from typing import Callable, Mapping
from urllib.parse import quote

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
    "checkout.completed": "order.paid",
    "subscription.paid": "order.paid",
    "subscription.active": "subscription.active",
    "subscription.canceled": "subscription.canceled",
    "subscription.expired": "subscription.canceled",
}


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:300]
    except Exception:
        return ""


def creem_get_any_mode(path: str, api_key: str) -> dict:
    """GET `path` against Creem's sandbox base, falling back to live.

    A Creem API key is bound to one mode (test/live have separate
    product/customer pools -- see authn/creem_access.py), and Creem gives no
    documented way to tell which mode a key belongs to from the key string
    itself. Rather than ask the tenant to declare it (error-prone -- easy to
    tick/untick the wrong box), just try both; whichever accepts the key is
    the tenant's actual mode. Mirrors authn/creem_access.py's
    validate_checkout_any_mode, which does the same trial-both-modes dance
    for PayGlue's own billing.
    """
    last_exc: Exception | None = None
    for base in ("https://test-api.creem.io", "https://api.creem.io"):
        req = urllib.request.Request(
            f"{base}{path}",
            headers={
                "x-api-key": api_key,
                "Accept": "application/json",
                # Creem's API sits behind Cloudflare, which blocks Python's
                # default "Python-urllib/3.x" User-Agent as a bot signature
                # (Cloudflare error 1010) -- same header authn/creem_access.py
                # already uses for PayGlue's own billing calls, which don't
                # hit this.
                "User-Agent": "PayGlue/1.0 (https://payglue.io)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                last_exc = exc
                continue
            raise
    raise last_exc or urllib.error.URLError("Creem API request failed in both modes.")


class CreemPaymentAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider,
        provider_key: str = "creem",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._raw_event_names = set(_EVENT_MAP.keys())
        self._supported_events = set(_EVENT_MAP.values())

    def _credentials(self, tenant_ctx: TenantContext) -> Mapping[str, str]:
        return self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )

    def health_check(self, tenant_ctx: TenantContext) -> dict[str, object]:
        credentials = self._credentials(tenant_ctx)
        api_key = credentials.get("api_key")
        if not api_key:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("api_key",),
            )

        try:
            creem_get_any_mode("/v1/products/search", api_key)
        except urllib.error.HTTPError as exc:
            # Report the real failure instead of masking it as missing
            # credentials -- credentials being present but rejected (wrong
            # key) is a different, more actionable message. Include Creem's
            # own error body (not just the status code) since it usually
            # names the actual problem (invalid key, wrong scope, etc.).
            detail = _read_error_body(exc)
            message = f"Creem API error: HTTP {exc.code}."
            if detail:
                message += f" {detail}"
            return {"ok": False, "code": "api_error", "message": message}
        except Exception as exc:
            return {"ok": False, "code": "api_error", "message": f"Creem API call failed: {exc}"}

        return {
            "ok": True,
            "code": "ok",
            "message": "Creem API key verified successfully.",
        }

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> None:
        credentials = self._credentials(tenant_ctx)
        webhook_secret = credentials.get("webhook_secret")
        if not webhook_secret:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("webhook_secret",),
            )

        signature = None
        for key, value in headers.items():
            if key.lower() == "creem-signature":
                signature = value
                break

        # Unlike Gumroad/Paddle, Creem reliably signs every delivery (already
        # relied on for PayGlue's own billing webhook -- see
        # creem_webhook.py::verify_signature, same HMAC-SHA256-of-raw-body
        # scheme). Require it here, don't treat it as optional.
        if not signature:
            raise InvalidWebhookSignatureError("missing creem-signature header")

        expected = hmac.new(
            webhook_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
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

        event_type = payload.get("eventType") or payload.get("type")
        if not isinstance(event_type, str) or not event_type:
            raise InvalidWebhookPayloadError("missing eventType")
        if event_type not in self._raw_event_names:
            raise UnsupportedEventTypeError(event_type)

        obj = payload.get("object")
        if not isinstance(obj, dict):
            raise InvalidWebhookPayloadError("missing object")

        event_id = str(payload.get("id") or obj.get("id") or "")
        if not event_id:
            raise InvalidWebhookPayloadError("missing event id")

        email = self._resolve_email(obj.get("customer"), tenant_ctx)
        if not email:
            raise InvalidWebhookPayloadError("missing customer email")

        product = obj.get("product")
        product_id = product.get("id") if isinstance(product, dict) else product
        if not product_id:
            order = obj.get("order") if isinstance(obj.get("order"), dict) else {}
            product_id = order.get("product") or event_id

        order = obj.get("order") if isinstance(obj.get("order"), dict) else {}
        currency = str(obj.get("currency") or order.get("currency") or "USD").upper()
        try:
            amount_minor = int(obj.get("amount") or order.get("amount") or 0)
        except (TypeError, ValueError):
            amount_minor = 0

        customer_ref = obj.get("customer")
        external_id = (
            customer_ref.get("id")
            if isinstance(customer_ref, dict)
            else customer_ref
        )

        canonical_type = _EVENT_MAP[event_type]
        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=event_id,
            event_type=canonical_type,
            occurred_at=self._now(),
            customer=CanonicalCustomer(email=email, external_id=external_id),
            line_items=(
                CanonicalLineItem(
                    external_product_id=str(product_id),
                    quantity=1,
                    amount_minor=amount_minor,
                    currency=currency,
                ),
            ),
            status="paid" if canonical_type == "order.paid" else obj.get("status", "active"),
        )

    def _resolve_email(self, customer: object, tenant_ctx: TenantContext) -> str:
        if isinstance(customer, dict):
            email = customer.get("email")
            return str(email).strip().lower() if email else ""
        if not customer:
            return ""

        credentials = self._credentials(tenant_ctx)
        api_key = credentials.get("api_key")
        if not api_key:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("api_key",),
            )
        try:
            body = creem_get_any_mode(
                f"/v1/customers?customer_id={quote(str(customer))}", api_key
            )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise InvalidWebhookPayloadError(
                f"could not resolve customer {customer}: {exc}"
            ) from exc

        email = body.get("email")
        if not email:
            raise InvalidWebhookPayloadError(f"customer {customer} has no email on file")
        return str(email).strip().lower()

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._supported_events

    def supports_raw_event_type(self, raw_event_type: str) -> bool:
        return raw_event_type in self._raw_event_names

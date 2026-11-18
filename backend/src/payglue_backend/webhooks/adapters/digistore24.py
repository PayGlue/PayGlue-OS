# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""
Digistore24 adapter for tenant-connected Ghost blogs.

Digistore24 is a reseller and merchant of record. It reports orders through
its IPN ("instant payment notification"): an HTTP POST with form fields, one
call per order item. The connection type is "Generic".

Signature: the field `sha_sign` in the body, not a header. It is the SHA-512
of every non-empty field except `sha_sign` itself, sorted by name byte-wise,
each written as `name=value` followed by the IPN passphrase, in upper-case
hex. The documentation says to sort without regard to case; a real delivery
(18.11.2026, ipn_version 1.6) matched only the byte-wise order of
Digistore24's reference script, so that is the only one accepted.

Digistore24 expects the plain text `OK` as the answer to every IPN, or it
retries for days. The inbound view answers that way for this provider.

Event names and fields come from Digistore24's developer documentation (IPN
events, handling subscriptions) and its reference scripts. on_payment is
confirmed against a real test purchase (fixture
tests/fixtures/digistore24/on_payment_test_subscription.txt). The other
events are confirmed as real deliveries come in.

Digistore24 also copies the query of the IPN address (`tenant`, `key`) into
the form fields it signs.

Mapping:
- on_payment: access. It comes for the first payment and for every renewal.
- on_rebill_cancelled: kept in the event log, no access change. The
  subscription is stopped but already paid for; Digistore24 sends
  last_paid_day when the paid period is over.
- last_paid_day: ends access.
- on_refund, on_chargeback: end access right away.
- on_payment_missed: kept in the event log, no access change. Digistore24 retries and reminds the buyer; if
  that fails it cancels and sends last_paid_day (PG-275: payment trouble is
  not an ending).
- on_rebill_resumed: kept in the event log; access follows with the next
  on_payment.
- Everything else (connection_test, affiliations, ...) is acknowledged and
  not stored.

`api_mode=test` marks a test purchase made with the "Testpay" method.
"""
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, time
from typing import Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

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

API_BASE = "https://www.digistore24.com/api/call"

# Digistore24 reports its times in the account's time zone, which is
# Europe/Berlin for the accounts this was built against. Used only when a
# timestamp carries no offset of its own.
_DS24_TZ = ZoneInfo("Europe/Berlin")

_HANDLED = {
    "on_payment": "order.paid",
    "last_paid_day": "subscription.revoked",
    "on_refund": "subscription.revoked",
    "on_chargeback": "subscription.revoked",
}

# Received, verified and kept in the event log, but no access change. Each
# reason says why, so the log answers the question a publisher will ask.
_NOTED = {
    "on_rebill_cancelled": "subscription stopped, access continues until last_paid_day",
    "on_payment_missed": "payment missed, Digistore24 retries; access ends only with last_paid_day",
    "on_rebill_resumed": "subscription resumed, access follows with the next on_payment",
}

_SIGNATURE_FIELDS = ("sha_sign", "SHASIGN")


def ds24_signature(fields: Iterable[tuple[str, str]], passphrase: str, *, case_sensitive: bool = True) -> str:
    """The `sha_sign` Digistore24 computes for these fields.

    Mirrors `digistore_signature()` from Digistore24's reference script:
    drop the signature fields and every empty value, sort by name, append
    `name=value` plus the passphrase for each, SHA-512, upper case. With
    `case_sensitive=False` the names are compared upper-cased, which is what
    the documentation describes.
    """
    items = [
        (name, value)
        for name, value in fields
        if name not in _SIGNATURE_FIELDS and value != ""
    ]
    if case_sensitive:
        items.sort(key=lambda item: item[0])
    else:
        items.sort(key=lambda item: item[0].upper())
    joined = "".join(f"{name}={value}{passphrase}" for name, value in items)
    return hashlib.sha512(joined.encode("utf-8")).hexdigest().upper()


def ds24_call(function: str, api_key: str, params: Mapping[str, str] | None = None) -> dict:
    """Call one API function and return its `data`.

    Digistore24 reports most errors with HTTP 200 and `result: error`, so the
    result field decides, not the status code. Raises RuntimeError with the
    message Digistore24 gave.
    """
    body = urllib.parse.urlencode(dict(params)).encode("utf-8") if params else None
    req = urllib.request.Request(
        f"{API_BASE}/{function}",
        data=body,
        headers={
            "X-DS-API-KEY": api_key,
            "Accept": "application/json",
            "User-Agent": "PayGlue/1.0 (https://payglue.io)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except Exception:  # noqa: BLE001 - not JSON, report the status
            raise RuntimeError(f"Digistore24 API error: HTTP {exc.code}") from exc
    if not isinstance(payload, dict) or payload.get("result") != "success":
        message = payload.get("message") if isinstance(payload, dict) else None
        raise RuntimeError(f"Digistore24 API error: {message or 'unknown error'}")
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def clean_api_key(value: str) -> str:
    """The key without whitespace and control characters.

    A key pasted from a terminal can carry an escape sequence, for example the
    one an arrow key sends, and Digistore24 then answers with a bare HTTP 400
    instead of an error message.
    """
    value = value or ""
    # ESC [ ... final byte: drop whole terminal escape sequences first.
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\x1b":
            i += 1
            if i < len(value) and value[i] == "[":
                i += 1
                while i < len(value) and not ("@" <= value[i] <= "~"):
                    i += 1
            i += 1
            continue
        if ch.isprintable() and not ch.isspace():
            out.append(ch)
        i += 1
    return "".join(out)


class Digistore24PaymentAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider,
        provider_key: str = "digistore24",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._now = now or (lambda: datetime.now(tz=UTC))
        self._raw_event_names = set(_HANDLED) | set(_NOTED)
        self._supported_events = set(_HANDLED.values())

    def _credentials(self, tenant_ctx: TenantContext) -> Mapping[str, str]:
        return self._credential_provider.get_credentials(
            tenant_ctx=tenant_ctx, provider_key=self._provider_key
        )

    def health_check(self, tenant_ctx: TenantContext) -> dict[str, object]:
        api_key = clean_api_key(self._credentials(tenant_ctx).get("api_key") or "")
        if not api_key:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("api_key",),
            )
        try:
            # The answer also carries the account's contact details and its
            # thank-you page key. Only the account name and the key's
            # permission level are used; nothing else is kept or logged.
            info = ds24_call("getUserInfo", api_key)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return {"ok": False, "code": "api_error", "message": str(exc)}
        user_name = str(info.get("user_name") or "")
        permissions = str(info.get("api_key_permissions") or "")
        if permissions != "writable":
            return {
                "ok": False,
                "code": "read_only_key",
                "message": (
                    "Digistore24 API key is valid but read-only. Create a key with full access "
                    "so PayGlue can set up the IPN connection."
                ),
            }
        label = f" ({user_name})" if user_name else ""
        return {"ok": True, "code": "ok", "message": f"Digistore24 API key verified{label}."}

    # The events PayGlue asks Digistore24 to send. Order events only; the
    # affiliation, e-ticket and custom form categories stay off.
    IPN_TRANSACTIONS = (
        "payment",
        "refund",
        "chargeback",
        "payment_missed",
        "rebill_cancelled",
        "rebill_resumed",
        "last_paid_day",
    )

    @staticmethod
    def ipn_domain_id(tenant_slug: str) -> str:
        """The key Digistore24 files our IPN connection under. One per
        publication, so saving again replaces the connection instead of
        adding a second one."""
        return f"payglue-{tenant_slug}"

    def register_ipn(
        self, tenant_ctx: TenantContext, ipn_url: str, passphrase: str
    ) -> dict[str, object]:
        """Create or replace the publication's IPN connection in Digistore24.

        Digistore24 has a settings page for this, but the passphrase has to
        match on both sides and the event list is easy to get wrong, so
        PayGlue sets it up through `ipnSetup` with the key the publisher
        saved. Needs a key with full access.
        """
        api_key = clean_api_key(self._credentials(tenant_ctx).get("api_key") or "")
        if not api_key:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("api_key",),
            )
        ds24_call(
            "ipnSetup",
            api_key,
            {
                "ipn_url": ipn_url,
                "name": "PayGlue",
                "product_ids": "all",
                "domain_id": self.ipn_domain_id(tenant_ctx.tenant_slug),
                "categories": "orders",
                "transactions": ",".join(self.IPN_TRANSACTIONS),
                "timing": "before_thankyou",
                "sha_passphrase": passphrase,
            },
        )
        return {"registered": ["ipn"], "failed": []}

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> None:
        passphrase = self._credentials(tenant_ctx).get("webhook_secret")
        if not passphrase:
            raise MissingCredentialsError(
                tenant_slug=tenant_ctx.tenant_slug,
                provider_key=self._provider_key,
                missing_fields=("webhook_secret",),
            )
        fields = self._decode_fields(raw_body)
        provided = next((value for name, value in fields if name == "sha_sign"), "") or next(
            (value for name, value in fields if name == "SHASIGN"), ""
        )
        if not provided:
            raise InvalidWebhookSignatureError("missing sha_sign field")
        expected = ds24_signature(fields, str(passphrase))
        # Compared as bytes, see PG-384.
        if not secrets.compare_digest(provided.strip().upper().encode("utf-8"), expected.encode("utf-8")):
            raise InvalidWebhookSignatureError("signature mismatch")

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> CanonicalPaymentEvent:
        data = dict(self._decode_fields(raw_body))
        raw_type = data.get("event") or ""
        if raw_type in _NOTED:
            raise UnsupportedEventTypeError(_NOTED[raw_type])
        if raw_type not in _HANDLED:
            raise UnsupportedEventTypeError(str(raw_type) or "missing event")

        order_id = data.get("order_id") or ""
        if not order_id:
            raise InvalidWebhookPayloadError("missing order_id")

        product_ids = self._product_ids(data)
        if not product_ids:
            raise InvalidWebhookPayloadError("cannot resolve product_id")

        currency = str(data.get("transaction_currency") or data.get("currency") or "EUR").upper()
        amount_minor = self._amount_minor(data.get("transaction_amount") or data.get("amount_brutto"))

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            provider_event_id=self._event_id(raw_type, data, order_id),
            event_type=_HANDLED[raw_type],
            occurred_at=self._occurred_at(raw_type, data),
            customer=self._customer(data),
            line_items=tuple(
                CanonicalLineItem(
                    external_product_id=pid,
                    quantity=1,
                    amount_minor=amount_minor if len(product_ids) == 1 else 0,
                    currency=currency,
                )
                for pid in product_ids
            ),
            status=self._status(raw_type, data),
            is_test=str(data.get("api_mode") or "").lower() == "test",
        )

    @staticmethod
    def _decode_fields(raw_body: bytes) -> list[tuple[str, str]]:
        try:
            text = raw_body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidWebhookPayloadError("payload is not valid UTF-8 form data") from exc
        fields = urllib.parse.parse_qsl(text, keep_blank_values=True)
        if not fields:
            raise InvalidWebhookPayloadError("payload is not form data")
        return fields

    @staticmethod
    def _product_ids(data: Mapping[str, str]) -> list[str]:
        """`product_id`, plus `product_id_2`, `product_id_3`, ... for further
        items. Digistore24 sends one IPN per item, but lists the others in some
        payloads; granting a product twice changes nothing downstream."""
        ids: list[str] = []
        first = (data.get("product_id") or "").strip()
        if first:
            ids.append(first)
        n = 2
        while True:
            extra = data.get(f"product_id_{n}")
            if extra is None:
                break
            extra = extra.strip()
            if extra and extra not in ids:
                ids.append(extra)
            n += 1
        return ids

    @staticmethod
    def _event_id(raw_type: str, data: Mapping[str, str], order_id: str) -> str:
        """Stable across Digistore24's retries, unique per business event.

        A payment or refund has its own transaction id. last_paid_day has
        none; it happens once per order, so the order id identifies it."""
        transaction_id = data.get("transaction_id") or ""
        if raw_type == "last_paid_day" or not transaction_id:
            sequence = data.get("pay_sequence_no") or ""
            suffix = f":{sequence}" if raw_type != "last_paid_day" and sequence else ""
            return f"{order_id}:{raw_type}{suffix}"
        return f"{transaction_id}:{raw_type}"

    @staticmethod
    def _customer(data: Mapping[str, str]) -> CanonicalCustomer:
        email = str(data.get("email") or data.get("buyer_email") or "").strip().lower()
        if not email:
            raise InvalidWebhookPayloadError("missing buyer email")
        name = " ".join(
            part for part in (data.get("address_first_name"), data.get("address_last_name")) if part
        ).strip()
        return CanonicalCustomer(
            email=email,
            external_id=str(data.get("buyer_id") or "") or None,
            name=name or None,
        )

    @staticmethod
    def _amount_minor(value: object) -> int:
        try:
            return round(float(str(value).replace(",", ".")) * 100) if value not in (None, "") else 0
        except ValueError:
            return 0

    def _occurred_at(self, raw_type: str, data: Mapping[str, str]) -> datetime:
        # Date and time come as separate fields, in the account's time zone.
        for date_field, time_field in (("transaction_date", "transaction_time"), ("order_date", "order_time")):
            day = (data.get(date_field) or "").strip()
            clock = (data.get(time_field) or "").strip()
            parsed = self._parse_time(f"{day} {clock}".strip()) if day else None
            if parsed:
                return parsed
        return self._now()

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(text[:10]), time())
            except ValueError:
                return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=_DS24_TZ)

    @staticmethod
    def _status(raw_type: str, data: Mapping[str, str]) -> str:
        if raw_type == "on_payment":
            return "paid"
        if raw_type == "on_refund":
            return "refunded"
        if raw_type == "on_chargeback":
            return "chargeback"
        return str(data.get("billing_status") or "expired")

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._supported_events

    def supports_raw_event_type(self, raw_event_type: str) -> bool:
        return raw_event_type in self._raw_event_names

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-123: Patreon as a tenant-facing payment provider.

Unlike every other provider here, Patreon is membership/tier-based, not
one-off-product-based, and it puts the trigger type in a header
(``X-Patreon-Event``, e.g. ``members:pledge:create``) rather than in the
body. The body is JSON:API (``data``/``attributes``/``relationships`` +
``included``).

Mapping model (confirmed with André, 2026-07-18):
- Grant is tier-specific: a patron entitled to tier X grants whatever Ghost
  access the creator mapped tier X to. One canonical line item per tier id
  in ``currently_entitled_tiers``.
- Revoke is all-or-nothing: any cancellation (``members:pledge:delete`` or a
  status change to ``former_patron``/``declined_patron``) revokes *all* of
  that member's Patreon-granted access. This deliberately does NOT rely on
  the tier id being present on the delete payload -- Patreon's docs don't
  document whether ``currently_entitled_tiers`` survives a delete, so we
  don't build on that unknown. The revoke-all is driven purely by the
  documented trigger header + ``patron_status``; the resolver
  (DbProductMappingResolver) turns a canonical ``subscription.canceled``
  event with no line items into a revoke of every active Patreon mapping
  for the tenant.

Signature: HMAC-MD5 of the raw body keyed with the webhook secret, hex
digest, in the ``X-Patreon-Signature`` header. MD5 is Patreon's choice, not
ours -- we match their scheme, same as every other adapter matches its
provider's (the per-tenant webhook URL is the real secret either way, see
ARCHITECTURE.md §5).
"""
from datetime import UTC, datetime
import hashlib
import hmac
import json
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

# Patreon trigger (X-Patreon-Event header) -> our canonical event. The actual
# grant-vs-revoke decision also consults patron_status below, since an
# "update" can mean either a new active pledge or a lapse.
_GRANT_TRIGGERS = {"members:pledge:create", "members:create"}
_REVOKE_TRIGGERS = {"members:pledge:delete", "members:delete"}
_STATUS_DEPENDENT_TRIGGERS = {"members:pledge:update", "members:update"}
_ALL_TRIGGERS = _GRANT_TRIGGERS | _REVOKE_TRIGGERS | _STATUS_DEPENDENT_TRIGGERS

_ACTIVE_STATUSES = {"active_patron"}
_LAPSED_STATUSES = {"former_patron", "declined_patron"}

_EVENT_ACTIVE = "subscription.active"
_EVENT_CANCELED = "subscription.canceled"
_SUPPORTED_EVENTS = {_EVENT_ACTIVE, _EVENT_CANCELED}

_EVENT_HEADER = "x-patreon-event"
_SIGNATURE_HEADER = "x-patreon-signature"


class PatreonPaymentAdapter:
    def __init__(
        self,
        credential_provider: CredentialProvider,
        provider_key: str = "patreon",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._credential_provider = credential_provider
        self._provider_key = provider_key
        self._now = now or (lambda: datetime.now(tz=UTC))

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
            "message": "Patreon webhook secret is configured. Send a test webhook from Patreon to confirm delivery.",
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

        signature = self._header(headers, _SIGNATURE_HEADER)
        if not signature:
            raise InvalidWebhookSignatureError("missing X-Patreon-Signature header")

        expected = hmac.new(
            webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.md5,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            raise InvalidWebhookSignatureError("signature mismatch")

    def parse_event(
        self, raw_body: bytes, headers: Mapping[str, str], tenant_ctx: TenantContext
    ) -> CanonicalPaymentEvent:
        trigger = self._header(headers, _EVENT_HEADER)
        if not trigger or trigger not in _ALL_TRIGGERS:
            raise UnsupportedEventTypeError(f"unsupported patreon trigger '{trigger}'")

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise InvalidWebhookPayloadError("payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise InvalidWebhookPayloadError("payload must be a JSON object")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise InvalidWebhookPayloadError("missing data object")

        member_id = str(data.get("id", ""))
        if not member_id:
            raise InvalidWebhookPayloadError("missing data.id")

        attrs = data.get("attributes")
        if not isinstance(attrs, dict):
            raise InvalidWebhookPayloadError("missing data.attributes")

        patron_status = attrs.get("patron_status")
        canonical_type = self._canonical_type(trigger, patron_status)

        email = attrs.get("email") or self._email_from_included(payload)
        if not email:
            # Patreon only includes the email when the webhook's client was
            # granted the campaigns.members[email] scope. Without it we can't
            # match a Ghost member, so fail loud rather than silently no-op.
            raise InvalidWebhookPayloadError(
                "missing member email -- webhook needs the members email scope"
            )

        full_name = attrs.get("full_name")
        occurred_at = self._parse_timestamp(
            attrs.get("last_charge_date") or attrs.get("pledge_relationship_start")
        )

        return CanonicalPaymentEvent(
            provider=self._provider_key,
            # Patreon sends no per-delivery event id, and the same member id
            # recurs across create/update/delete. Key idempotency on
            # member+trigger+timestamp so a genuine re-subscribe (a second
            # pledge:create for the same member, later) isn't mistaken for a
            # duplicate of the first.
            provider_event_id=f"{member_id}:{trigger}:{occurred_at.isoformat()}",
            event_type=canonical_type,
            occurred_at=occurred_at,
            customer=CanonicalCustomer(email=str(email), external_id=member_id, name=full_name),
            # On a revoke we deliberately emit NO line items -- the resolver
            # turns a subscription.canceled event with no line items into a
            # revoke of every active Patreon mapping for the tenant (revoke-all
            # semantics, tier-independent). On a grant we emit one line item
            # per entitled tier id.
            line_items=(
                self._tier_line_items(data) if canonical_type == _EVENT_ACTIVE else ()
            ),
            status="active" if canonical_type == _EVENT_ACTIVE else "canceled",
        )

    @staticmethod
    def _canonical_type(trigger: str, patron_status: object) -> str:
        if trigger in _REVOKE_TRIGGERS:
            return _EVENT_CANCELED
        if trigger in _GRANT_TRIGGERS:
            return _EVENT_ACTIVE
        # status-dependent (pledge:update / members:update): a lapse to
        # former/declined is a revoke; anything else with an active status is
        # a grant. Unknown/None status on an update is treated as a revoke --
        # safer to remove access than to leave a lapsed patron entitled.
        if patron_status in _ACTIVE_STATUSES:
            return _EVENT_ACTIVE
        if patron_status in _LAPSED_STATUSES:
            return _EVENT_CANCELED
        return _EVENT_CANCELED

    @staticmethod
    def _tier_line_items(data: dict) -> tuple[CanonicalLineItem, ...]:
        relationships = data.get("relationships")
        tier_ids: list[str] = []
        if isinstance(relationships, dict):
            entitled = relationships.get("currently_entitled_tiers")
            if isinstance(entitled, dict):
                rows = entitled.get("data")
                if isinstance(rows, list):
                    tier_ids = [
                        str(row.get("id"))
                        for row in rows
                        if isinstance(row, dict) and row.get("id")
                    ]
        if not tier_ids:
            # An active pledge with no resolvable tier can't be mapped to a
            # Ghost entitlement -- surface it rather than granting nothing
            # silently.
            raise InvalidWebhookPayloadError(
                "active pledge has no currently_entitled_tiers to map"
            )
        return tuple(
            CanonicalLineItem(
                external_product_id=tier_id,
                quantity=1,
                amount_minor=0,
                currency="USD",
            )
            for tier_id in tier_ids
        )

    @staticmethod
    def _email_from_included(payload: dict) -> str | None:
        # Some webhook configurations surface the email on the related user
        # object in `included` rather than on the member's attributes.
        included = payload.get("included")
        if not isinstance(included, list):
            return None
        for item in included:
            if not isinstance(item, dict) or item.get("type") != "user":
                continue
            attrs = item.get("attributes")
            if isinstance(attrs, dict) and attrs.get("email"):
                return str(attrs["email"])
        return None

    def supports_event(self, event_type: str) -> bool:
        return event_type in _SUPPORTED_EVENTS

    def supports_raw_event_type(self, raw_event_type: str) -> bool:
        return raw_event_type in _ALL_TRIGGERS

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str | None:
        for key, value in headers.items():
            if key.lower() == name:
                return value
        return None

    def _parse_timestamp(self, value: object) -> datetime:
        if isinstance(value, str) and value:
            parsed = value[:-1] + "+00:00" if value.endswith("Z") else value
            try:
                dt = datetime.fromisoformat(parsed)
                return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
            except ValueError:
                pass
        return self._now()

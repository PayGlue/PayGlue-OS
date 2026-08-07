# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-123: Patreon adapter. Trigger type comes from the X-Patreon-Event
header, body is JSON:API, signature is HMAC-MD5. Grant is tier-specific
(one line item per entitled tier); revoke is all-or-nothing (no line items,
resolver revokes everything for the provider)."""
from datetime import UTC, datetime
import hashlib
import hmac
import json

import pytest

from payglue_backend.core.errors import (
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    MissingCredentialsError,
    UnsupportedEventTypeError,
)
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters.patreon import PatreonPaymentAdapter

SECRET = "whsec_patreon_test"


class StubCredentialProvider:
    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        self._credentials = credentials if credentials is not None else {"webhook_secret": SECRET}

    def get_credentials(self, tenant_ctx: TenantContext, provider_key: str) -> dict[str, str]:
        assert tenant_ctx.tenant_slug == "tenant-a"
        assert provider_key == "patreon"
        return dict(self._credentials)


def _adapter(now=None) -> PatreonPaymentAdapter:
    return PatreonPaymentAdapter(credential_provider=StubCredentialProvider(), now=now)


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode("utf-8"), body, hashlib.md5).hexdigest()


def _member_body(
    *,
    member_id: str = "m_1",
    patron_status: str = "active_patron",
    email: str = "patron@example.com",
    tier_ids: list[str] | None = None,
) -> bytes:
    tiers = tier_ids if tier_ids is not None else ["tier_1"]
    payload = {
        "data": {
            "type": "member",
            "id": member_id,
            "attributes": {
                "patron_status": patron_status,
                "email": email,
                "full_name": "A Patron",
                "last_charge_date": "2026-01-01T12:00:00Z",
            },
            "relationships": {
                "currently_entitled_tiers": {
                    "data": [{"type": "tier", "id": t} for t in tiers]
                },
            },
        }
    }
    return json.dumps(payload).encode("utf-8")


def _headers(trigger: str, body: bytes) -> dict[str, str]:
    return {"X-Patreon-Event": trigger, "X-Patreon-Signature": _sign(body)}


def _ctx() -> TenantContext:
    return TenantContext(tenant_slug="tenant-a")


# --- signature verification ---


def test_verify_accepts_matching_md5_signature() -> None:
    body = _member_body()
    _adapter().verify_webhook(body, _headers("members:pledge:create", body), _ctx())


def test_verify_rejects_mismatched_signature() -> None:
    body = _member_body()
    headers = {"X-Patreon-Event": "members:pledge:create", "X-Patreon-Signature": "deadbeef"}
    with pytest.raises(InvalidWebhookSignatureError):
        _adapter().verify_webhook(body, headers, _ctx())


def test_verify_rejects_missing_signature_header() -> None:
    body = _member_body()
    with pytest.raises(InvalidWebhookSignatureError):
        _adapter().verify_webhook(body, {"X-Patreon-Event": "members:pledge:create"}, _ctx())


def test_verify_raises_on_missing_credentials() -> None:
    adapter = PatreonPaymentAdapter(credential_provider=StubCredentialProvider(credentials={}))
    body = _member_body()
    with pytest.raises(MissingCredentialsError):
        adapter.verify_webhook(body, _headers("members:pledge:create", body), _ctx())


# --- grant path (tier-specific) ---


def test_pledge_create_grants_with_one_line_item_per_tier() -> None:
    body = _member_body(tier_ids=["tier_1", "tier_2"])
    event = _adapter().parse_event(body, _headers("members:pledge:create", body), _ctx())

    assert event.event_type == "subscription.active"
    assert event.customer.email == "patron@example.com"
    assert event.customer.external_id == "m_1"
    assert {li.external_product_id for li in event.line_items} == {"tier_1", "tier_2"}


def test_pledge_update_active_patron_grants() -> None:
    body = _member_body(patron_status="active_patron")
    event = _adapter().parse_event(body, _headers("members:pledge:update", body), _ctx())
    assert event.event_type == "subscription.active"
    assert len(event.line_items) == 1


def test_active_pledge_without_tiers_is_rejected() -> None:
    body = _member_body(tier_ids=[])
    with pytest.raises(InvalidWebhookPayloadError):
        _adapter().parse_event(body, _headers("members:pledge:create", body), _ctx())


# --- revoke path (all-or-nothing, no line items) ---


def test_pledge_delete_revokes_with_no_line_items() -> None:
    body = _member_body(patron_status="former_patron", tier_ids=[])
    event = _adapter().parse_event(body, _headers("members:pledge:delete", body), _ctx())
    assert event.event_type == "subscription.canceled"
    assert event.line_items == ()


def test_update_to_former_patron_revokes() -> None:
    body = _member_body(patron_status="former_patron", tier_ids=[])
    event = _adapter().parse_event(body, _headers("members:pledge:update", body), _ctx())
    assert event.event_type == "subscription.canceled"
    assert event.line_items == ()


def test_update_to_declined_patron_revokes() -> None:
    body = _member_body(patron_status="declined_patron", tier_ids=[])
    event = _adapter().parse_event(body, _headers("members:pledge:update", body), _ctx())
    assert event.event_type == "subscription.canceled"


def test_update_with_unknown_status_defaults_to_revoke() -> None:
    body = _member_body(patron_status="", tier_ids=[])
    event = _adapter().parse_event(body, _headers("members:update", body), _ctx())
    assert event.event_type == "subscription.canceled"


# --- misc ---


def test_email_falls_back_to_included_user() -> None:
    payload = {
        "data": {
            "type": "member",
            "id": "m_9",
            "attributes": {"patron_status": "active_patron", "last_charge_date": "2026-01-01T12:00:00Z"},
            "relationships": {"currently_entitled_tiers": {"data": [{"type": "tier", "id": "tier_1"}]}},
        },
        "included": [
            {"type": "user", "id": "u_1", "attributes": {"email": "from-included@example.com"}}
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    event = _adapter().parse_event(body, _headers("members:pledge:create", body), _ctx())
    assert event.customer.email == "from-included@example.com"


def test_missing_email_is_rejected() -> None:
    payload = {
        "data": {
            "type": "member",
            "id": "m_2",
            "attributes": {"patron_status": "active_patron"},
            "relationships": {"currently_entitled_tiers": {"data": [{"type": "tier", "id": "tier_1"}]}},
        }
    }
    body = json.dumps(payload).encode("utf-8")
    with pytest.raises(InvalidWebhookPayloadError):
        _adapter().parse_event(body, _headers("members:pledge:create", body), _ctx())


def test_unsupported_trigger_is_rejected() -> None:
    body = _member_body()
    with pytest.raises(UnsupportedEventTypeError):
        _adapter().parse_event(body, _headers("posts:publish", body), _ctx())


def test_missing_trigger_header_is_rejected() -> None:
    body = _member_body()
    with pytest.raises(UnsupportedEventTypeError):
        _adapter().parse_event(body, {"X-Patreon-Signature": _sign(body)}, _ctx())


def test_provider_event_id_differs_across_triggers_for_same_member() -> None:
    fixed_now = datetime(2026, 1, 1, tzinfo=UTC)
    adapter = _adapter(now=lambda: fixed_now)
    create_body = _member_body(member_id="m_5")
    delete_body = _member_body(member_id="m_5", patron_status="former_patron", tier_ids=[])
    create = adapter.parse_event(create_body, _headers("members:pledge:create", create_body), _ctx())
    delete = adapter.parse_event(delete_body, _headers("members:pledge:delete", delete_body), _ctx())
    assert create.provider_event_id != delete.provider_event_id


def test_supports_event_and_raw_event_type() -> None:
    adapter = _adapter()
    assert adapter.supports_event("subscription.active")
    assert adapter.supports_event("subscription.canceled")
    assert not adapter.supports_event("order.paid")
    assert adapter.supports_raw_event_type("members:pledge:delete")
    assert not adapter.supports_raw_event_type("posts:publish")


def test_health_check_ok_when_secret_present() -> None:
    result = _adapter().health_check(_ctx())
    assert result["ok"] is True


def test_health_check_raises_without_secret() -> None:
    adapter = PatreonPaymentAdapter(credential_provider=StubCredentialProvider(credentials={}))
    with pytest.raises(MissingCredentialsError):
        adapter.health_check(_ctx())

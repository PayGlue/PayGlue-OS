# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Cancel-subscription action on the Billing page's Danger Zone."""
from dataclasses import dataclass

import pytest
from django.test import Client

from payglue_backend.tenants.models import BillingAccount, Plan, Tenant, TenantMembership, UserProfile


pytestmark = pytest.mark.django_db

CANCEL_URL = "/t/tenant-a/api/v1/billing/creem-cancel-subscription"
SUBSCRIPTION_URL = "/t/tenant-a/api/v1/billing/creem-subscription"


@dataclass(frozen=True)
class _StubClaims:
    firebase_uid: str
    email: str


class _StubVerifier:
    def __init__(self, claims: _StubClaims) -> None:
        self._claims = claims

    def verify(self, token: str) -> _StubClaims:
        del token
        return self._claims


def _auth_headers(monkeypatch: pytest.MonkeyPatch, profile: UserProfile) -> dict[str, str]:
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(_StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


def _owner_and_tenant(
    role: str = TenantMembership.Role.OWNER, creem_subscription_id: str = ""
) -> UserProfile:
    solo = Plan.objects.get(key="solo")
    owner = UserProfile.objects.create(firebase_uid="uid-cancel-owner", email="cancel-owner@example.com")
    billing_account = BillingAccount.objects.create(
        owner=owner, plan=solo, creem_subscription_id=creem_subscription_id
    )
    tenant = Tenant.objects.create(
        slug="tenant-a", schema_name="tenant_a", billing_account=billing_account
    )
    TenantMembership.objects.create(tenant=tenant, user_profile=owner, role=role)
    return owner


def _mock_creem_search(monkeypatch: pytest.MonkeyPatch, *, subscription_id: str = "sub_1") -> list:
    """Mocks the legacy /v1/subscriptions/search path (no stored
    creem_subscription_id on BillingAccount -- PG-149's original scenario)."""
    calls: list = []

    def _fake_get(url: str, api_key: str) -> dict:
        if "/v1/customers" in url:
            return {"id": "cust_1"}
        if "/v1/subscriptions/search" in url:
            return {"items": [{"id": subscription_id, "customer": "cust_1", "status": "active"}]}
        raise AssertionError(f"unexpected GET {url}")

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        calls.append((url, body))
        return {"id": subscription_id, "status": "canceled", "current_period_end_date": "2026-08-01T00:00:00Z"}

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)
    return calls


def test_owner_can_cancel_active_subscription_via_legacy_search(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """No creem_subscription_id stored yet (pre-PG-142 account) -- falls
    back to the unfiltered search, same as before this fix."""
    settings.CREEM_API_KEY = "sk_live"
    settings.CREEM_SANDBOX_API_KEY = ""
    owner = _owner_and_tenant()
    headers = _auth_headers(monkeypatch, owner)
    calls = _mock_creem_search(monkeypatch)

    resp = Client().post(CANCEL_URL, **headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"
    assert len(calls) == 1
    url, body = calls[0]
    assert url.endswith("/v1/subscriptions/sub_1/cancel")
    assert body == {"mode": "scheduled"}


def test_direct_subscription_id_lookup_is_preferred_over_search(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """PG-142+: once BillingAccount.creem_subscription_id is set, both the
    subscription GET and the cancel action use it directly instead of the
    unreliable unfiltered/paginated search -- this is the real fix for a
    real subscription that simply wasn't on page 1 of that search."""
    settings.CREEM_API_KEY = "sk_live"
    settings.CREEM_SANDBOX_API_KEY = ""
    owner = _owner_and_tenant(creem_subscription_id="sub_direct")
    headers = _auth_headers(monkeypatch, owner)

    search_was_called = False

    def _fake_get(url: str, api_key: str) -> dict:
        nonlocal search_was_called
        if url.endswith("/v1/subscriptions?subscription_id=sub_direct"):
            return {"id": "sub_direct", "status": "active", "customer": {"id": "cust_1"}}
        if "/v1/subscriptions/search" in url:
            search_was_called = True
            return {"items": []}
        raise AssertionError(f"unexpected GET {url}")

    cancel_calls: list = []

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        cancel_calls.append((url, body))
        return {"id": "sub_direct", "status": "canceled", "current_period_end_date": "2026-08-01T00:00:00Z"}

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    sub_resp = Client().get(SUBSCRIPTION_URL, **headers)
    assert sub_resp.status_code == 200
    assert sub_resp.json()["subscriptions"] == [{"id": "sub_direct", "status": "active", "customer": {"id": "cust_1"}}]
    assert search_was_called is False

    cancel_resp = Client().post(CANCEL_URL, **headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "canceled"
    # The GET above also triggers a portal-link POST (/v1/customers/billing),
    # so filter down to the actual cancel call rather than counting all POSTs.
    cancel_endpoint_calls = [c for c in cancel_calls if c[0].endswith("/v1/subscriptions/sub_direct/cancel")]
    assert len(cancel_endpoint_calls) == 1
    assert cancel_endpoint_calls[0][1] == {"mode": "scheduled"}


def test_owner_can_cancel_via_transaction_fallback_when_search_is_empty(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """Found live (PG-141 test): /v1/subscriptions/search came back
    genuinely empty for a real, active subscription -- CreemSubscriptionView
    and the switch endpoint already fall through to the transaction-based
    lookup for this, but this view still had its own older two-tier copy
    of the logic and 404'd on exactly the same subscription those two
    could already find. Must use the same three-tier lookup."""
    settings.CREEM_API_KEY = "sk_live"
    settings.CREEM_SANDBOX_API_KEY = ""
    owner = _owner_and_tenant()
    headers = _auth_headers(monkeypatch, owner)

    def _fake_get(url: str, api_key: str) -> dict:
        if "/v1/customers" in url:
            return {"id": "cust_1"}
        if "/v1/subscriptions/search" in url:
            return {"items": []}
        if "/v1/transactions/search" in url:
            return {"items": [{"id": "txn_1", "customer": "cust_1", "subscription": "sub_via_txn"}]}
        if url.endswith("/v1/subscriptions?subscription_id=sub_via_txn"):
            return {"id": "sub_via_txn", "status": "trialing", "customer": {"id": "cust_1"}}
        raise AssertionError(f"unexpected GET {url}")

    cancel_calls: list = []

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        cancel_calls.append((url, body))
        return {"id": "sub_via_txn", "status": "canceled", "current_period_end_date": "2026-08-01T00:00:00Z"}

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = Client().post(CANCEL_URL, **headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "canceled"
    cancel_endpoint_calls = [c for c in cancel_calls if c[0].endswith("/v1/subscriptions/sub_via_txn/cancel")]
    assert len(cancel_endpoint_calls) == 1


def test_support_readonly_cannot_cancel(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    settings.CREEM_API_KEY = "sk_live"
    settings.CREEM_SANDBOX_API_KEY = ""
    owner = _owner_and_tenant(role=TenantMembership.Role.SUPPORT_READONLY)
    headers = _auth_headers(monkeypatch, owner)
    _mock_creem_search(monkeypatch)

    resp = Client().post(CANCEL_URL, **headers)

    assert resp.status_code == 403


def test_404_when_no_active_subscription(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    settings.CREEM_API_KEY = "sk_live"
    settings.CREEM_SANDBOX_API_KEY = ""
    owner = _owner_and_tenant()
    headers = _auth_headers(monkeypatch, owner)

    def _fake_get(url: str, api_key: str) -> dict:
        if "/v1/customers" in url:
            return {"id": "cust_1"}
        if "/v1/subscriptions/search" in url:
            return {"items": []}
        if "/v1/transactions/search" in url:
            return {"items": []}
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)

    resp = Client().post(CANCEL_URL, **headers)

    assert resp.status_code == 404

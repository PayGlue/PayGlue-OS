# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Found live (PG-141 test): a brand-new BillingAccount is provisioned with
the safe "founding" placeholder plan (see TenantCreateSerializer -- no live
Creem lookup happens at signup time), so a real Studio/Solo/Agency
subscriber's dashboard showed "Founding Member" until they happened to do an
explicit plan switch. CreemSubscriptionView now self-heals that placeholder
to the real plan the moment it reads a matching active/trialing
subscription, piggybacking on the Creem API call it already makes for the
"Your Subscription" card -- no extra request, and it only ever touches the
"founding" placeholder, never a plan someone is genuinely on."""
from dataclasses import dataclass

import pytest
from django.test import Client

from payglue_backend.tenants.models import BillingAccount, Plan, Tenant, TenantMembership, UserProfile


pytestmark = pytest.mark.django_db

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


def _owner_and_tenant(plan_key: str = "founding", creem_subscription_id: str = "") -> UserProfile:
    plan = Plan.objects.get(key=plan_key)
    owner = UserProfile.objects.create(firebase_uid="uid-plan-sync", email="plan-sync@example.com")
    billing_account = BillingAccount.objects.create(
        owner=owner, plan=plan, creem_subscription_id=creem_subscription_id
    )
    tenant = Tenant.objects.create(
        slug="tenant-a", schema_name="tenant_a", billing_account=billing_account
    )
    TenantMembership.objects.create(tenant=tenant, user_profile=owner, role=TenantMembership.Role.OWNER)
    return owner


def test_syncs_founding_placeholder_from_direct_subscription_lookup(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    settings.CREEM_API_KEY = "sk_test"
    studio_product_id = Plan.objects.get(key="studio").creem_product_id
    owner = _owner_and_tenant(plan_key="founding", creem_subscription_id="sub_1")
    headers = _auth_headers(monkeypatch, owner)

    def _fake_get(url: str, api_key: str) -> dict:
        if url.endswith("/v1/subscriptions?subscription_id=sub_1"):
            return {
                "id": "sub_1",
                "status": "active",
                "customer": {"id": "cust_1"},
                "product": {"id": studio_product_id, "name": "Subscription payment"},
            }
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._post",
        lambda url, api_key, body: {"customer_portal_link": "https://creem.io/portal/1"},
    )

    resp = Client().get(SUBSCRIPTION_URL, **headers)

    assert resp.status_code == 200
    billing_account = BillingAccount.objects.get(owner=owner)
    assert billing_account.plan.key == "studio"


def test_syncs_founding_placeholder_from_items_product_id_when_no_top_level_product(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """Creem's schema documents subscription.product as oneOf ProductEntity |
    string, but doesn't guarantee it's populated on every response shape --
    items[].product_id is the other, always-string source for the same
    information. Must still resolve the plan from that when "product"
    itself is missing entirely."""
    settings.CREEM_API_KEY = "sk_test"
    agency_product_id = Plan.objects.get(key="agency").creem_product_id
    owner = _owner_and_tenant(plan_key="founding", creem_subscription_id="sub_1")
    headers = _auth_headers(monkeypatch, owner)

    def _fake_get(url: str, api_key: str) -> dict:
        if url.endswith("/v1/subscriptions?subscription_id=sub_1"):
            return {
                "id": "sub_1",
                "status": "active",
                "customer": {"id": "cust_1"},
                "items": [{"id": "sitem_1", "product_id": agency_product_id}],
            }
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._post",
        lambda url, api_key, body: {"customer_portal_link": "https://creem.io/portal/1"},
    )

    resp = Client().get(SUBSCRIPTION_URL, **headers)

    assert resp.status_code == 200
    billing_account = BillingAccount.objects.get(owner=owner)
    assert billing_account.plan.key == "agency"


def test_syncs_founding_placeholder_via_search_fallback(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """No stored creem_subscription_id yet (the exact gap this test session
    found for a brand-new signup's first purchase) -- must still self-heal
    via the same search fallback the switch endpoint uses."""
    settings.CREEM_API_KEY = "sk_test"
    solo_product_id = Plan.objects.get(key="solo").creem_product_id
    owner = _owner_and_tenant(plan_key="founding", creem_subscription_id="")
    headers = _auth_headers(monkeypatch, owner)

    def _fake_get(url: str, api_key: str) -> dict:
        if "/v1/customers" in url:
            return {"id": "cust_1"}
        if "/v1/subscriptions/search" in url:
            return {
                "items": [
                    {
                        "id": "sub_new",
                        "customer": "cust_1",
                        "status": "trialing",
                        "product": {"id": solo_product_id, "name": "Subscription payment"},
                    }
                ]
            }
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._post",
        lambda url, api_key, body: {"customer_portal_link": "https://creem.io/portal/1"},
    )

    resp = Client().get(SUBSCRIPTION_URL, **headers)

    assert resp.status_code == 200
    billing_account = BillingAccount.objects.get(owner=owner)
    assert billing_account.plan.key == "solo"


def test_syncs_founding_placeholder_via_transaction_fallback_when_search_is_empty(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """Found live (PG-141 test): /v1/subscriptions/search came back
    genuinely empty for a real, active Studio subscriber -- not a wrong
    match, zero items at all (the exact failure PG-147/PG-149's docstring
    already warned the unfiltered single-page search could hit). Must fall
    through to /v1/transactions/search (reliably customer-scoped, confirmed
    live) to find the subscription id from a real transaction, then fetch
    that subscription directly by id."""
    settings.CREEM_API_KEY = "sk_test"
    studio_product_id = Plan.objects.get(key="studio").creem_product_id
    owner = _owner_and_tenant(plan_key="founding", creem_subscription_id="")
    headers = _auth_headers(monkeypatch, owner)

    def _fake_get(url: str, api_key: str) -> dict:
        if "/v1/customers" in url:
            return {"id": "cust_1"}
        if "/v1/subscriptions/search" in url:
            return {"items": []}
        if "/v1/transactions/search" in url:
            return {
                "items": [
                    {"id": "txn_1", "customer": "cust_1", "subscription": "sub_real", "amount": 3900}
                ]
            }
        if url.endswith("/v1/subscriptions?subscription_id=sub_real"):
            return {
                "id": "sub_real",
                "status": "trialing",
                "customer": {"id": "cust_1"},
                "product": {"id": studio_product_id, "name": "Subscription payment"},
            }
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._post",
        lambda url, api_key, body: {"customer_portal_link": "https://creem.io/portal/1"},
    )

    resp = Client().get(SUBSCRIPTION_URL, **headers)

    assert resp.status_code == 200
    billing_account = BillingAccount.objects.get(owner=owner)
    assert billing_account.plan.key == "studio"


def test_does_not_touch_a_plan_that_is_not_the_founding_placeholder(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """A real, already-set plan (from an explicit switch, or genuinely a
    legacy Founding Member with no matching subscription) must never be
    silently overwritten by this read-path heal."""
    settings.CREEM_API_KEY = "sk_test"
    studio_product_id = Plan.objects.get(key="studio").creem_product_id
    owner = _owner_and_tenant(plan_key="solo", creem_subscription_id="sub_1")
    headers = _auth_headers(monkeypatch, owner)

    def _fake_get(url: str, api_key: str) -> dict:
        if url.endswith("/v1/subscriptions?subscription_id=sub_1"):
            return {
                "id": "sub_1",
                "status": "active",
                "customer": {"id": "cust_1"},
                "product": {"id": studio_product_id, "name": "Subscription payment"},
            }
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._post",
        lambda url, api_key, body: {"customer_portal_link": "https://creem.io/portal/1"},
    )

    resp = Client().get(SUBSCRIPTION_URL, **headers)

    assert resp.status_code == 200
    billing_account = BillingAccount.objects.get(owner=owner)
    assert billing_account.plan.key == "solo"


def test_leaves_founding_placeholder_alone_when_product_matches_no_plan(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    settings.CREEM_API_KEY = "sk_test"
    owner = _owner_and_tenant(plan_key="founding", creem_subscription_id="sub_1")
    headers = _auth_headers(monkeypatch, owner)

    def _fake_get(url: str, api_key: str) -> dict:
        if url.endswith("/v1/subscriptions?subscription_id=sub_1"):
            return {
                "id": "sub_1",
                "status": "active",
                "customer": {"id": "cust_1"},
                "product": {"id": "prod_unknown", "name": "Subscription payment"},
            }
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._post",
        lambda url, api_key, body: {"customer_portal_link": "https://creem.io/portal/1"},
    )

    resp = Client().get(SUBSCRIPTION_URL, **headers)

    assert resp.status_code == 200
    billing_account = BillingAccount.objects.get(owner=owner)
    assert billing_account.plan.key == "founding"

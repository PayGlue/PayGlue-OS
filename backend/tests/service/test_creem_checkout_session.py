# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-150: in-dashboard checkout session creation for plan upgrades."""
from dataclasses import dataclass

import pytest
from django.test import Client

from payglue_backend.authn.creem_access import CreemAccessError
from payglue_backend.tenants.models import BillingAccount, Plan, Tenant, TenantMembership, UserProfile

# Which hosts may be a checkout return target now comes from configuration
# rather than a baked-in list (PG-238), so these tests have to say where the
# dashboard lives. Without it the allowlist is loopback only, which is exactly
# what a fresh self-hosted install sees.
@pytest.fixture(autouse=True)
def _dashboard_address(settings):
    settings.PUBLIC_APP_BASE_URL = "https://dashboard.example.com"
    settings.CHECKOUT_RETURN_HOSTS = ""



pytestmark = pytest.mark.django_db


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


def _owner_and_tenant(tenant_slug: str) -> tuple[UserProfile, Tenant]:
    solo = Plan.objects.get(key="solo")
    owner = UserProfile.objects.create(
        firebase_uid=f"uid-{tenant_slug}", email=f"{tenant_slug}@example.com"
    )
    billing_account = BillingAccount.objects.create(owner=owner, plan=solo)
    tenant = Tenant.objects.create(
        slug=tenant_slug,
        schema_name=tenant_slug.replace("-", "_"),
        billing_account=billing_account,
    )
    TenantMembership.objects.create(tenant=tenant, user_profile=owner, role=TenantMembership.Role.OWNER)
    return owner, tenant


def _post_checkout(client: Client, tenant: Tenant, headers: dict, body: dict):
    return client.post(
        f"/t/{tenant.slug}/api/v1/billing/creem-checkout-session",
        data=body,
        content_type="application/json",
        **headers,
    )


def test_rejects_invalid_plan_key(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-bad-plan")
    headers = _auth_headers(monkeypatch, owner)
    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "not-a-plan", "interval": "monthly", "return_url": "https://dashboard.example.com/t/x/billing"},
    )
    assert resp.status_code == 400


def test_rejects_return_url_on_untrusted_host(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-bad-host")
    headers = _auth_headers(monkeypatch, owner)
    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "studio", "interval": "monthly", "return_url": "https://evil.example.com/steal"},
    )
    assert resp.status_code == 400


def test_creates_checkout_session_for_valid_plan(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-ok")
    headers = _auth_headers(monkeypatch, owner)

    captured = {}

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        captured["url"] = url
        captured["api_key"] = api_key
        captured["body"] = body
        return {"checkout_url": "https://creem.io/checkout/sess_123"}

    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "studio", "interval": "monthly", "return_url": f"https://dashboard.example.com/t/{tenant.slug}/billing"},
    )

    assert resp.status_code == 200
    assert resp.json()["checkout_url"] == "https://creem.io/checkout/sess_123"
    assert captured["body"]["product_id"] == Plan.objects.get(key="studio").creem_product_id
    assert captured["body"]["success_url"] == f"https://dashboard.example.com/t/{tenant.slug}/billing"
    assert captured["body"]["customer"]["email"] == owner.email


def test_creates_checkout_session_for_annual_interval(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-annual")
    headers = _auth_headers(monkeypatch, owner)

    captured = {}

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        captured["body"] = body
        return {"checkout_url": "https://creem.io/checkout/sess_456"}

    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "agency", "interval": "annual", "return_url": f"https://dashboard.example.com/t/{tenant.slug}/billing"},
    )

    assert resp.status_code == 200
    assert captured["body"]["product_id"] == Plan.objects.get(key="agency").creem_product_id_annual


def test_503_when_checkout_not_configured(monkeypatch: pytest.MonkeyPatch, settings) -> None:
    settings.CREEM_API_KEY = ""
    owner, tenant = _owner_and_tenant("checkout-unconfigured")
    headers = _auth_headers(monkeypatch, owner)
    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "studio", "interval": "monthly", "return_url": f"https://dashboard.example.com/t/{tenant.slug}/billing"},
    )
    assert resp.status_code == 503


def test_switches_existing_subscription_in_place_with_proration(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """PG-150 follow-up, found live: creating a brand new checkout per plan
    switch left the old subscription running and billing in parallel with
    the new one. Creem has a real in-place update endpoint that prorates
    correctly and never creates a second subscription -- use that whenever
    the caller already has one, instead of a fresh checkout session."""
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-switch-in-place")
    headers = _auth_headers(monkeypatch, owner)

    billing_account = BillingAccount.objects.get(owner=owner)
    billing_account.creem_subscription_id = "sub_existing"
    billing_account.save()

    def _fake_get(url: str, api_key: str) -> dict:
        if url.endswith("/v1/subscriptions?subscription_id=sub_existing"):
            return {
                "id": "sub_existing",
                "status": "active",
                "customer": {"id": "cust_1"},
                "items": [{"id": "sitem_1", "product_id": "prod_solo"}],
            }
        raise AssertionError(f"unexpected GET {url}")

    captured = {}

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        captured["url"] = url
        captured["body"] = body
        return {"id": "sub_existing", "status": "active", "product": {"id": "prod_studio"}}

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "studio", "interval": "monthly", "return_url": f"https://dashboard.example.com/t/{tenant.slug}/billing"},
    )

    assert resp.status_code == 200
    assert resp.json()["updated"] is True
    assert captured["url"].endswith("/v1/subscriptions/sub_existing")
    # Must target the subscription's existing item by ID -- Creem creates a
    # *new* item instead of replacing it if the id is omitted (verified
    # against the OpenAPI spec: UpsertSubscriptionItemEntity.id "the id of
    # the item to update").
    assert captured["body"]["items"] == [
        {"product_id": Plan.objects.get(key="studio").creem_product_id, "id": "sitem_1"}
    ]
    assert captured["body"]["update_behavior"] == "proration-charge-immediately"
    billing_account.refresh_from_db()
    assert billing_account.plan.key == "studio"


def test_switches_in_place_via_search_fallback_when_stored_id_is_missing(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """Found live (PG-141 test): a customer's very first Creem purchase never
    goes through the dashboard_upgrade webhook branch that populates
    creem_subscription_id -- only a later in-dashboard switch does. Without
    falling back to the email-based search here too, that first switch
    wrongly concluded "no existing subscription" and created a second,
    parallel checkout instead of swapping in place, leaving both
    subscriptions alive and un-cancelled. Must find it via search and swap
    in place, same as the direct-ID path."""
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-legacy-search-fallback")
    headers = _auth_headers(monkeypatch, owner)

    def _fake_get(url: str, api_key: str) -> dict:
        if "/v1/customers" in url:
            return {"id": "cust_1"}
        if "/v1/subscriptions/search" in url:
            return {"items": [{"id": "sub_legacy", "customer": "cust_1", "status": "active"}]}
        raise AssertionError(f"unexpected GET {url}")

    captured = {}

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        captured["url"] = url
        captured["body"] = body
        return {"id": "sub_legacy", "status": "active"}

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "studio", "interval": "monthly", "return_url": f"https://dashboard.example.com/t/{tenant.slug}/billing"},
    )

    assert resp.status_code == 200
    assert resp.json()["updated"] is True
    assert captured["url"].endswith("/v1/subscriptions/sub_legacy")
    # Backfilled so the *next* switch takes the fast direct-by-ID path
    # instead of needing this same search fallback again.
    billing_account = BillingAccount.objects.get(owner=owner)
    assert billing_account.plan.key == "studio"
    assert billing_account.creem_subscription_id == "sub_legacy"
    assert billing_account.creem_customer_id == "cust_1"


def test_switches_in_place_via_search_fallback_when_stored_id_is_already_canceled(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """Found live: BillingAccount.creem_subscription_id pointed at a
    subscription the customer had already cancelled (e.g. via the Danger
    Zone) -- the direct lookup still finds it (dead), which must not be
    treated as "no existing subscription" or "the subscription to swap".
    Must fall through to the search and swap the real, still-active one
    it finds there instead."""
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-stale-stored-id")
    headers = _auth_headers(monkeypatch, owner)

    billing_account = BillingAccount.objects.get(owner=owner)
    billing_account.creem_subscription_id = "sub_dead"
    billing_account.save()

    def _fake_get(url: str, api_key: str) -> dict:
        if url.endswith("/v1/subscriptions?subscription_id=sub_dead"):
            return {"id": "sub_dead", "status": "canceled", "customer": {"id": "cust_1"}}
        if "/v1/customers" in url:
            return {"id": "cust_1"}
        if "/v1/subscriptions/search" in url:
            return {"items": [{"id": "sub_really_active", "customer": "cust_1", "status": "active"}]}
        raise AssertionError(f"unexpected GET {url}")

    captured = {}

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        captured["url"] = url
        captured["body"] = body
        return {"id": "sub_really_active", "status": "active"}

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "agency", "interval": "monthly", "return_url": f"https://dashboard.example.com/t/{tenant.slug}/billing"},
    )

    assert resp.status_code == 200
    assert resp.json()["updated"] is True
    assert captured["url"].endswith("/v1/subscriptions/sub_really_active")
    billing_account.refresh_from_db()
    assert billing_account.plan.key == "agency"
    assert billing_account.creem_subscription_id == "sub_really_active"


def test_in_place_switch_omits_item_id_when_subscription_has_no_items(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """Defensive fallback: if Creem's response is missing/has an empty
    items array for some reason, still send the update rather than crash --
    just without the item id (matches the original, pre-fix behavior)."""
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-no-items")
    headers = _auth_headers(monkeypatch, owner)

    billing_account = BillingAccount.objects.get(owner=owner)
    billing_account.creem_subscription_id = "sub_no_items"
    billing_account.save()

    def _fake_get(url: str, api_key: str) -> dict:
        if url.endswith("/v1/subscriptions?subscription_id=sub_no_items"):
            return {"id": "sub_no_items", "status": "active", "customer": {"id": "cust_1"}}
        raise AssertionError(f"unexpected GET {url}")

    captured = {}

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        captured["body"] = body
        return {"id": "sub_no_items", "status": "active"}

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "studio", "interval": "monthly", "return_url": f"https://dashboard.example.com/t/{tenant.slug}/billing"},
    )

    assert resp.status_code == 200
    assert captured["body"]["items"] == [{"product_id": Plan.objects.get(key="studio").creem_product_id}]


def test_in_place_switch_surfaces_unexpected_errors_as_400(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """A non-CreemAccessError exception (e.g. a malformed response causing
    a JSON/KeyError) must not bubble up as a raw 500/connection failure --
    caught, logged, and turned into a normal error response."""
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-unexpected-error")
    headers = _auth_headers(monkeypatch, owner)

    billing_account = BillingAccount.objects.get(owner=owner)
    billing_account.creem_subscription_id = "sub_boom"
    billing_account.save()

    def _fake_get(url: str, api_key: str) -> dict:
        if url.endswith("/v1/subscriptions?subscription_id=sub_boom"):
            return {"id": "sub_boom", "status": "active", "customer": {"id": "cust_1"}}
        raise AssertionError(f"unexpected GET {url}")

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        raise ValueError("boom")

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "studio", "interval": "monthly", "return_url": f"https://dashboard.example.com/t/{tenant.slug}/billing"},
    )

    assert resp.status_code == 400
    assert "unexpected" in resp.json()["detail"].lower()


def test_in_place_switch_gives_actionable_message_for_active_discount(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """Creem refuses to swap items in place while a discount/coupon is active
    on the subscription -- the customer can't remove a coupon themselves
    (only cancel or pause), so the raw Creem error text must be replaced
    with guidance to cancel and resubscribe instead."""
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-active-discount")
    headers = _auth_headers(monkeypatch, owner)

    billing_account = BillingAccount.objects.get(owner=owner)
    billing_account.creem_subscription_id = "sub_discounted"
    billing_account.save()

    def _fake_get(url: str, api_key: str) -> dict:
        if url.endswith("/v1/subscriptions?subscription_id=sub_discounted"):
            return {
                "id": "sub_discounted",
                "status": "active",
                "customer": {"id": "cust_1"},
                "items": [{"id": "sitem_1", "product_id": "prod_solo"}],
            }
        raise AssertionError(f"unexpected GET {url}")

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        raise CreemAccessError(
            'Creem API 400: {"status":400,"error":"Bad Request",'
            '"message":["This subscription cannot be modified while a discount is active."]}'
        )

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "studio", "interval": "monthly", "return_url": f"https://dashboard.example.com/t/{tenant.slug}/billing"},
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "discount" in detail.lower()
    assert "cancel" in detail.lower()


def test_in_place_switch_gives_actionable_message_for_trialing_subscription(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """Found live (PG-141 test): Creem refuses to swap items in place while
    a subscription is still "trialing" (only "active" ones can be
    modified) -- there's nothing the customer can do about that from our
    dashboard either, so the raw Creem error text must be replaced with
    the same kind of actionable guidance as the discount case."""
    settings.CREEM_API_KEY = "sk_test"
    owner, tenant = _owner_and_tenant("checkout-trialing")
    headers = _auth_headers(monkeypatch, owner)

    billing_account = BillingAccount.objects.get(owner=owner)
    billing_account.creem_subscription_id = "sub_trialing"
    billing_account.save()

    def _fake_get(url: str, api_key: str) -> dict:
        if url.endswith("/v1/subscriptions?subscription_id=sub_trialing"):
            return {
                "id": "sub_trialing",
                "status": "trialing",
                "customer": {"id": "cust_1"},
                "items": [{"id": "sitem_1", "product_id": "prod_solo"}],
            }
        raise AssertionError(f"unexpected GET {url}")

    def _fake_post(url: str, api_key: str, body: dict) -> dict:
        raise CreemAccessError(
            'Creem API 400: {"status":400,"error":"Bad Request",'
            '"message":["This subscription must be active before it can be modified."]}'
        )

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)
    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _post_checkout(
        Client(), tenant, headers,
        {"plan_key": "studio", "interval": "monthly", "return_url": f"https://dashboard.example.com/t/{tenant.slug}/billing"},
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "trial" in detail.lower()
    assert "support" in detail.lower()
    assert f"/t/{tenant.slug}/support" in detail

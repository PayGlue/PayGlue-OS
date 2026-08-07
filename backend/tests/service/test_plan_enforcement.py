from dataclasses import dataclass

import pytest
from django.test import Client

from payglue_backend.tenants.models import BillingAccount, Plan, Tenant, TenantMembership, UserProfile
from payglue_backend.webhooks.models import BuyButton, IntegrationConfig, PaywallConfig, PricingTable


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


def _owner_on_solo_plan(tenant_slug: str) -> tuple[UserProfile, Tenant]:
    """A tenant on the Solo plan (1 of everything), owned by a fresh user."""
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


def test_paywall_create_blocked_at_plan_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, tenant = _owner_on_solo_plan("plan-pw")
    headers = _auth_headers(monkeypatch, owner)
    client = Client()

    resp1 = client.post(
        f"/t/{tenant.slug}/api/v1/paywalls",
        data={"name": "First paywall"},
        content_type="application/json",
        **headers,
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        f"/t/{tenant.slug}/api/v1/paywalls",
        data={"name": "Second paywall"},
        content_type="application/json",
        **headers,
    )
    assert resp2.status_code == 402
    assert resp2.json()["upgrade_required"] is True
    assert PaywallConfig.objects.filter(tenant_slug=tenant.slug).count() == 1


def test_buy_button_create_blocked_at_plan_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, tenant = _owner_on_solo_plan("plan-bb")
    headers = _auth_headers(monkeypatch, owner)
    client = Client()

    resp1 = client.post(
        f"/t/{tenant.slug}/api/v1/buttons",
        data={"name": "First button"},
        content_type="application/json",
        **headers,
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        f"/t/{tenant.slug}/api/v1/buttons",
        data={"name": "Second button"},
        content_type="application/json",
        **headers,
    )
    assert resp2.status_code == 402
    assert BuyButton.objects.filter(tenant_slug=tenant.slug).count() == 1


def test_pricing_table_create_blocked_at_plan_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, tenant = _owner_on_solo_plan("plan-pt")
    headers = _auth_headers(monkeypatch, owner)
    client = Client()

    resp1 = client.post(
        f"/t/{tenant.slug}/api/v1/pricing-tables",
        data={"name": "First table"},
        content_type="application/json",
        **headers,
    )
    assert resp1.status_code == 201

    resp2 = client.post(
        f"/t/{tenant.slug}/api/v1/pricing-tables",
        data={"name": "Second table"},
        content_type="application/json",
        **headers,
    )
    assert resp2.status_code == 402
    assert PricingTable.objects.filter(tenant_slug=tenant.slug).count() == 1


def test_team_member_create_blocked_at_plan_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, tenant = _owner_on_solo_plan("plan-team")
    headers = _auth_headers(monkeypatch, owner)
    client = Client()

    # Owner already counts as the tenant's 1 team member on the Solo plan.
    second_profile = UserProfile.objects.create(firebase_uid="uid-second", email="second@example.com")

    resp = client.post(
        f"/t/{tenant.slug}/api/v1/team",
        data={"email": second_profile.email, "role": "admin"},
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 402
    assert resp.json()["upgrade_required"] is True
    assert TenantMembership.objects.filter(tenant=tenant).count() == 1


def test_new_tenant_create_blocked_at_plan_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, _tenant = _owner_on_solo_plan("plan-solo-only")
    headers = _auth_headers(monkeypatch, owner)
    client = Client()

    # Owner already has 1/1 tenants on the Solo plan.
    resp = client.post(
        "/api/v1/tenants",
        data={"slug": "plan-solo-second"},
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 402
    assert not Tenant.objects.filter(slug="plan-solo-second").exists()


def test_provider_connect_blocked_at_plan_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, tenant = _owner_on_solo_plan("plan-prov")
    headers = _auth_headers(monkeypatch, owner)
    client = Client()

    # Solo allows 2 payment providers. Pre-fill both so the next connect 402s.
    IntegrationConfig.objects.create(
        tenant_slug=tenant.slug, provider_key="polar", provider_type="polar", enabled=True
    )
    IntegrationConfig.objects.create(
        tenant_slug=tenant.slug, provider_key="paypal", provider_type="paypal", enabled=True
    )

    resp = client.put(
        f"/t/{tenant.slug}/api/v1/integrations/gumroad",
        data={"enabled": True, "provider_type": "gumroad"},
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 402
    assert not IntegrationConfig.objects.filter(tenant_slug=tenant.slug, provider_key="gumroad").exists()


def test_provider_update_not_blocked_when_already_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Updating an existing connection must never 402, even at the limit."""
    owner, tenant = _owner_on_solo_plan("plan-prov-upd")
    headers = _auth_headers(monkeypatch, owner)
    client = Client()

    IntegrationConfig.objects.create(
        tenant_slug=tenant.slug, provider_key="polar", provider_type="polar", enabled=True
    )
    IntegrationConfig.objects.create(
        tenant_slug=tenant.slug, provider_key="paypal", provider_type="paypal", enabled=True
    )

    resp = client.put(
        f"/t/{tenant.slug}/api/v1/integrations/polar",
        data={"enabled": False, "provider_type": "polar"},
        content_type="application/json",
        **headers,
    )
    assert resp.status_code == 200


def test_usage_endpoint_reports_used_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    owner, tenant = _owner_on_solo_plan("plan-usage")
    headers = _auth_headers(monkeypatch, owner)
    client = Client()

    resp = client.get(f"/t/{tenant.slug}/api/v1/billing/usage", **headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "solo"
    assert body["usage"]["team_members"] == {"used": 1, "limit": 1}  # owner counts
    assert body["usage"]["buy_buttons"] == {"used": 0, "limit": 1}
    assert body["usage"]["publications"] == {"used": 1, "limit": 1}


def test_unlimited_plan_never_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    agency = Plan.objects.get(key="agency")
    owner = UserProfile.objects.create(firebase_uid="uid-unlimited", email="unlimited@example.com")
    billing_account = BillingAccount.objects.create(owner=owner, plan=agency)
    tenant = Tenant.objects.create(
        slug="plan-unlimited", schema_name="plan_unlimited", billing_account=billing_account
    )
    TenantMembership.objects.create(tenant=tenant, user_profile=owner, role=TenantMembership.Role.OWNER)
    headers = _auth_headers(monkeypatch, owner)
    client = Client()

    for i in range(3):
        resp = client.post(
            f"/t/{tenant.slug}/api/v1/paywalls",
            data={"name": f"Paywall {i}"},
            content_type="application/json",
            **headers,
        )
        assert resp.status_code == 201
    assert PaywallConfig.objects.filter(tenant_slug=tenant.slug).count() == 3

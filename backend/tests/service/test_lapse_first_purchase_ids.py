# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-298: a first purchase has to leave its Creem ids on the account.

Found live: the checkout.completed webhook only wrote the subscription id
on the dashboard-upgrade branch. A brand-new buyer went through the
InvitationGrant branch, their BillingAccount was created later at the first
publication without any lookup, and the daily lifecycle poll skipped every
account without an id. Four paying founding members, none of them watched.

The chain now: webhook stores the ids on the grant, the first publication
copies them onto the BillingAccount, and a checkout for an account that
lapsed clears the lapse and resumes the paused workspaces."""
import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from payglue_backend.tenants.models import (
    BillingAccount,
    InvitationGrant,
    Plan,
    Tenant,
    TenantMembership,
    UserProfile,
)

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/v1/auth/webhooks/creem-checkout"


class _StubClaims:
    def __init__(self, firebase_uid: str, email: str) -> None:
        self.firebase_uid = firebase_uid
        self.email = email


class _StubVerifier:
    def __init__(self, claims: _StubClaims) -> None:
        self._claims = claims

    def verify(self, token: str) -> _StubClaims:
        del token
        return self._claims


def _auth_headers(monkeypatch: pytest.MonkeyPatch, firebase_uid: str, email: str) -> dict[str, str]:
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(_StubClaims(firebase_uid=firebase_uid, email=email)),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


def _signed_post(client: Client, secret: str, body: dict):
    raw = json.dumps(body).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return client.post(WEBHOOK_URL, data=raw, content_type="application/json", HTTP_CREEM_SIGNATURE=signature)


@pytest.fixture
def webhook_settings(settings):
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"
    return settings


def test_first_purchase_webhook_stores_ids_on_the_grant(webhook_settings) -> None:
    body = {
        "eventType": "checkout.completed",
        "object": {
            "customer": {"id": "cust_first", "email": "first@example.com"},
            "product": {"id": "prod_founding"},
            "subscription": {"id": "sub_first"},
        },
    }

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    grant = InvitationGrant.objects.get(email="first@example.com")
    assert grant.creem_customer_id == "cust_first"
    assert grant.creem_subscription_id == "sub_first"


def test_webhook_accepts_bare_id_strings(webhook_settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Creem sends related objects as plain ids on some deliveries."""
    monkeypatch.setattr(
        "payglue_backend.authn.views.resolve_customer_email", lambda customer, api_key, sandbox=False: "bare@example.com"
    )
    body = {
        "eventType": "checkout.completed",
        "object": {"customer": "cust_bare", "product": "prod_founding", "subscription": "sub_bare"},
    }

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    grant = InvitationGrant.objects.get(email="bare@example.com")
    assert grant.creem_customer_id == "cust_bare"
    assert grant.creem_subscription_id == "sub_bare"


def test_first_publication_copies_ids_onto_billing_account(monkeypatch: pytest.MonkeyPatch) -> None:
    InvitationGrant.objects.create(
        email="buyer@example.com",
        source=InvitationGrant.Source.CREEM_CHECKOUT,
        creem_customer_id="cust_buyer",
        creem_subscription_id="sub_buyer",
    )
    UserProfile.objects.create(firebase_uid="uid-buyer", email="buyer@example.com")
    headers = _auth_headers(monkeypatch, "uid-buyer", "buyer@example.com")

    resp = Client().post("/api/v1/tenants", data={"slug": "buyer-pub"}, content_type="application/json", **headers)

    assert resp.status_code == 201
    account = Tenant.objects.get(slug="buyer-pub").billing_account
    assert account.creem_customer_id == "cust_buyer"
    assert account.creem_subscription_id == "sub_buyer"
    # Starts as alive so the very next poll can already see a transition.
    assert account.last_known_subscription_status == "active"


def test_first_publication_without_grant_ids_stays_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Somebody provisioned by hand has no Creem ids. Nothing to copy, and
    the poll's email lookup is what would find them later, if anything."""
    InvitationGrant.objects.create(email="manual@example.com", source=InvitationGrant.Source.MANUAL)
    UserProfile.objects.create(firebase_uid="uid-manual", email="manual@example.com")
    headers = _auth_headers(monkeypatch, "uid-manual", "manual@example.com")

    resp = Client().post("/api/v1/tenants", data={"slug": "manual-pub"}, content_type="application/json", **headers)

    assert resp.status_code == 201
    account = Tenant.objects.get(slug="manual-pub").billing_account
    assert account.creem_subscription_id == ""
    assert account.last_known_subscription_status == ""


def test_checkout_for_lapsed_account_resumes_workspaces(webhook_settings) -> None:
    solo = Plan.objects.get(key="solo")
    owner = UserProfile.objects.create(firebase_uid="uid-lapsed", email="lapsed@example.com")
    account = BillingAccount.objects.create(
        owner=owner,
        plan=solo,
        creem_subscription_id="sub_dead",
        last_known_subscription_status="unpaid",
        payment_failed_detected_at=timezone.now() - timedelta(days=45),
        cancellation_detected_at=timezone.now() - timedelta(days=40),
        lapsed_at=timezone.now() - timedelta(days=3),
        needs_admin_review=True,
        admin_review_reason="not_found",
    )
    tenant = Tenant.objects.create(
        slug="lapsed-pub", schema_name="lapsed_pub", billing_account=account, status=Tenant.Status.PAUSED
    )
    TenantMembership.objects.create(tenant=tenant, user_profile=owner, role=TenantMembership.Role.OWNER)

    body = {
        "eventType": "checkout.completed",
        "object": {
            "customer": {"id": "cust_lapsed", "email": "lapsed@example.com"},
            "product": {"id": solo.creem_product_id},
            "subscription": {"id": "sub_new"},
            "metadata": {"source": "dashboard_upgrade", "billing_account_id": account.id},
        },
    }

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    account.refresh_from_db()
    tenant.refresh_from_db()
    assert account.creem_subscription_id == "sub_new"
    assert account.last_known_subscription_status == "active"
    assert account.payment_failed_detected_at is None
    assert account.cancellation_detected_at is None
    assert account.lapsed_at is None
    assert account.needs_admin_review is False
    assert tenant.status == Tenant.Status.ACTIVE


def test_backfill_command_stores_ids_and_status(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from django.core.management import call_command

    solo = Plan.objects.get(key="solo")
    owner = UserProfile.objects.create(firebase_uid="uid-old", email="old@example.com")
    account = BillingAccount.objects.create(owner=owner, plan=solo)
    monkeypatch.setattr(
        "payglue_backend.tenants.lapse.latest_creem_subscription_for_account",
        lambda acc: ({"id": "sub_old", "customer": "cust_old", "status": "unpaid"}, "sk", "https://x", False),
    )

    call_command("backfill_creem_subscription_ids", "--dry-run")
    account.refresh_from_db()
    assert account.creem_subscription_id == ""

    call_command("backfill_creem_subscription_ids", "--assume-active")
    account.refresh_from_db()
    assert account.creem_subscription_id == "sub_old"
    assert account.creem_customer_id == "cust_old"
    assert account.last_known_subscription_status == "active"
    assert "old@example.com" in capsys.readouterr().out

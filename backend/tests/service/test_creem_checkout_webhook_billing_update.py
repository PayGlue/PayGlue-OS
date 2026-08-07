# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-142: a checkout.completed webhook for an in-dashboard plan upgrade
(PG-150, tagged via metadata.source=dashboard_upgrade) must update the
purchasing customer's existing BillingAccount.plan directly -- it must NOT
just fall through to the InvitationGrant flow meant for brand-new signups."""
import hashlib
import hmac
import json

import pytest
from django.test import Client

from payglue_backend.tenants.models import BillingAccount, InvitationGrant, Plan, UserProfile


pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/v1/auth/webhooks/creem-checkout"


def _signed_post(client: Client, secret: str, body: dict):
    raw = json.dumps(body).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return client.post(
        WEBHOOK_URL,
        data=raw,
        content_type="application/json",
        HTTP_CREEM_SIGNATURE=signature,
    )


def _billing_account(email: str) -> BillingAccount:
    solo = Plan.objects.get(key="solo")
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    return BillingAccount.objects.create(owner=owner, plan=solo)


def _checkout_payload(customer_id: str, product_id: str, subscription_id: str, billing_account_id: int) -> dict:
    return {
        "eventType": "checkout.completed",
        "object": {
            "customer": {"id": customer_id, "email": "upgrader@example.com"},
            "product": {"id": product_id},
            "subscription": {"id": subscription_id},
            "metadata": {"source": "dashboard_upgrade", "billing_account_id": billing_account_id},
        },
    }


def test_dashboard_upgrade_webhook_updates_existing_billing_account(settings) -> None:
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    billing_account = _billing_account("upgrader@example.com")
    studio = Plan.objects.get(key="studio")

    body = _checkout_payload(
        customer_id="cust_123",
        product_id=studio.creem_product_id,
        subscription_id="sub_456",
        billing_account_id=billing_account.id,
    )

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    billing_account.refresh_from_db()
    assert billing_account.plan.key == "studio"
    assert billing_account.creem_customer_id == "cust_123"
    assert billing_account.creem_subscription_id == "sub_456"
    # This path is for existing customers, not new signups -- no invitation
    # grant should be created for a dashboard upgrade.
    assert not InvitationGrant.objects.filter(email="upgrader@example.com").exists()


def test_dashboard_upgrade_webhook_matches_annual_product_id(settings) -> None:
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    billing_account = _billing_account("annual-upgrader@example.com")
    agency = Plan.objects.get(key="agency")

    body = _checkout_payload(
        customer_id="cust_789",
        product_id=agency.creem_product_id_annual,
        subscription_id="sub_789",
        billing_account_id=billing_account.id,
    )

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    billing_account.refresh_from_db()
    assert billing_account.plan.key == "agency"


def test_dashboard_upgrade_cancels_the_previous_subscription_immediately(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """PG-150 follow-up, found live: switching Solo -> Studio left the Solo
    subscription active and still billing in parallel with the new one --
    Creem's checkout API never replaces an existing subscription on its
    own. The webhook must cancel the old one immediately once tagged via
    metadata.previous_subscription_id."""
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    billing_account = _billing_account("switcher@example.com")
    studio = Plan.objects.get(key="studio")

    body = {
        "eventType": "checkout.completed",
        "object": {
            "customer": {"id": "cust_123", "email": "switcher@example.com"},
            "product": {"id": studio.creem_product_id},
            "subscription": {"id": "sub_new"},
            "metadata": {
                "source": "dashboard_upgrade",
                "billing_account_id": billing_account.id,
                "previous_subscription_id": "sub_old",
            },
        },
    }

    cancel_calls: list = []

    def _fake_post(url: str, api_key: str, cancel_body: dict) -> dict:
        cancel_calls.append((url, cancel_body))
        return {"id": "sub_old", "status": "canceled"}

    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    billing_account.refresh_from_db()
    assert billing_account.plan.key == "studio"
    assert billing_account.creem_subscription_id == "sub_new"
    assert len(cancel_calls) == 1
    url, cancel_body = cancel_calls[0]
    assert url.endswith("/v1/subscriptions/sub_old/cancel")
    assert cancel_body == {"mode": "immediate"}


def test_dashboard_upgrade_does_not_cancel_when_no_previous_subscription(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """A first-time purchase (e.g. Founding Member -> Solo) has nothing to
    cancel -- must not call the cancel endpoint at all."""
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    billing_account = _billing_account("first-timer@example.com")
    studio = Plan.objects.get(key="studio")

    body = _checkout_payload(
        customer_id="cust_555",
        product_id=studio.creem_product_id,
        subscription_id="sub_first",
        billing_account_id=billing_account.id,
    )

    post_calls: list = []
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._post",
        lambda url, api_key, body: post_calls.append((url, body)) or {},
    )

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    assert post_calls == []


def test_non_dashboard_checkout_still_uses_invitation_grant_flow(settings) -> None:
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    body = {
        "eventType": "checkout.completed",
        "object": {
            "customer": {"id": "cust_new", "email": "newsignup@example.com"},
            "product": {"id": "prod_founding"},
        },
    }

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    assert InvitationGrant.objects.filter(email="newsignup@example.com").exists()


def test_new_signup_checkout_activates_the_license_at_creem(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """PG-201: most buyers return via the checkout redirect, which never carries
    the license key to the signup form -- so the license must be activated at
    Creem here in the checkout.completed webhook, not only at signup redemption.
    Otherwise every key stays 'Inactive (0/1)' in Creem's dashboard."""
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    calls: dict = {}

    def _fake_activate(key, instance_name, api_key, sandbox=False):
        calls.update(key=key, instance_name=instance_name)
        return {"instance": {"id": "inst_web"}}

    monkeypatch.setattr("payglue_backend.authn.views.activate_creem_license", _fake_activate)

    body = {
        "eventType": "checkout.completed",
        "object": {
            "customer": {"id": "cust_new", "email": "buyer-web@example.com"},
            "product": {"id": "prod_founding"},
            "license_keys": [{"key": "CREEM-WEBHOOK-KEY"}],
        },
    }

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    assert calls == {"key": "CREEM-WEBHOOK-KEY", "instance_name": "buyer-web@example.com"}
    grant = InvitationGrant.objects.get(email="buyer-web@example.com")
    assert grant.creem_license_instance_id == "inst_web"


def test_untagged_checkout_for_existing_customer_updates_billing_account_and_cancels_old_subscription(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """PG-184, found live: a checkout NOT started from our own Plans page
    (a direct/external Creem checkout link -- marketing email, sandbox test
    link, anything not tagged metadata.source=dashboard_upgrade) for an
    email that already has an account skipped the whole
    upgrade/downgrade-detection branch entirely and fell straight into the
    InvitationGrant flow meant for brand-new signups. That created a
    second, parallel subscription nothing ever linked to the existing
    BillingAccount or cancelled -- reproduced live with two simultaneously
    active sandbox subscriptions on the same test account."""
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    billing_account = _billing_account("existing-customer@example.com")
    billing_account.creem_subscription_id = "sub_old_untracked"
    billing_account.creem_customer_id = "cust_old"
    billing_account.save()
    studio = Plan.objects.get(key="studio")

    # No metadata at all -- exactly what a direct/external checkout link
    # produces, unlike the dashboard_upgrade-tagged flow.
    body = {
        "eventType": "checkout.completed",
        "object": {
            "customer": {"id": "cust_new", "email": "existing-customer@example.com"},
            "product": {"id": studio.creem_product_id},
            "subscription": {"id": "sub_new_direct"},
        },
    }

    cancel_calls: list = []

    def _fake_post(url: str, api_key: str, cancel_body: dict) -> dict:
        cancel_calls.append((url, cancel_body))
        return {"id": "sub_old_untracked", "status": "canceled"}

    monkeypatch.setattr("payglue_backend.authn.creem_access._post", _fake_post)

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    billing_account.refresh_from_db()
    assert billing_account.plan.key == "studio"
    assert billing_account.creem_customer_id == "cust_new"
    assert billing_account.creem_subscription_id == "sub_new_direct"
    # No InvitationGrant -- this is an existing customer, not a new signup.
    assert not InvitationGrant.objects.filter(email="existing-customer@example.com").exists()
    assert len(cancel_calls) == 1
    url, cancel_body = cancel_calls[0]
    assert url.endswith("/v1/subscriptions/sub_old_untracked/cancel")
    assert cancel_body == {"mode": "immediate"}


def test_untagged_checkout_for_existing_customer_with_no_prior_subscription_does_not_cancel(
    monkeypatch: pytest.MonkeyPatch, settings
) -> None:
    """An existing account with no previously-tracked Creem subscription
    (e.g. invited but never purchased before) has nothing to cancel --
    must not call the cancel endpoint at all."""
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    _billing_account("never-purchased@example.com")
    studio = Plan.objects.get(key="studio")

    body = {
        "eventType": "checkout.completed",
        "object": {
            "customer": {"id": "cust_new", "email": "never-purchased@example.com"},
            "product": {"id": studio.creem_product_id},
            "subscription": {"id": "sub_first_real"},
        },
    }

    post_calls: list = []
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._post",
        lambda url, api_key, body: post_calls.append((url, body)) or {},
    )

    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    assert post_calls == []

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-141: a checkout.completed webhook that changes a customer's plan
must flag downgrade_detected_at when the new plan ranks lower, and clear
it again if they upgrade back before enforcement ever runs."""
import hashlib
import hmac
import json

import pytest
from django.core import mail
from django.test import Client

from payglue_backend.tenants.models import BillingAccount, LifecycleEmailTemplate, Plan, UserProfile


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


def _billing_account(email: str, plan_key: str) -> BillingAccount:
    plan = Plan.objects.get(key=plan_key)
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    return BillingAccount.objects.create(owner=owner, plan=plan)


def _switch_payload(email: str, product_id: str, billing_account_id: int, subscription_id: str) -> dict:
    return {
        "eventType": "checkout.completed",
        "object": {
            "customer": {"id": "cust_1", "email": email},
            "product": {"id": product_id},
            "subscription": {"id": subscription_id},
            "metadata": {"source": "dashboard_upgrade", "billing_account_id": billing_account_id},
        },
    }


def test_downgrade_sets_downgrade_detected_at(settings) -> None:
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    billing_account = _billing_account("downgrader@example.com", "studio")
    solo = Plan.objects.get(key="solo")

    body = _switch_payload(
        "downgrader@example.com", solo.creem_product_id, billing_account.id, "sub_new"
    )
    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    billing_account.refresh_from_db()
    assert billing_account.plan.key == "solo"
    assert billing_account.downgrade_detected_at is not None


def test_upgrade_clears_downgrade_detected_at(settings) -> None:
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    billing_account = _billing_account("upgrader@example.com", "solo")
    billing_account.downgrade_detected_at = None
    billing_account.save()
    from django.utils import timezone

    billing_account.downgrade_detected_at = timezone.now()
    billing_account.save()

    studio = Plan.objects.get(key="studio")
    body = _switch_payload(
        "upgrader@example.com", studio.creem_product_id, billing_account.id, "sub_new"
    )
    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    billing_account.refresh_from_db()
    assert billing_account.plan.key == "studio"
    assert billing_account.downgrade_detected_at is None


def test_downgrade_sends_lifecycle_email_when_template_enabled(settings) -> None:
    """PG-148: fires at the same signal point as downgrade_detected_at,
    no separate webhook needed."""
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"
    LifecycleEmailTemplate.objects.filter(trigger="downgrade").update(enabled=True)

    billing_account = _billing_account("email-downgrader@example.com", "studio")
    solo = Plan.objects.get(key="solo")

    body = _switch_payload(
        "email-downgrader@example.com", solo.creem_product_id, billing_account.id, "sub_new"
    )
    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["email-downgrader@example.com"]


def test_upgrade_does_not_send_downgrade_email(settings) -> None:
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"
    LifecycleEmailTemplate.objects.filter(trigger="downgrade").update(enabled=True)

    billing_account = _billing_account("email-upgrader@example.com", "solo")
    studio = Plan.objects.get(key="studio")

    body = _switch_payload(
        "email-upgrader@example.com", studio.creem_product_id, billing_account.id, "sub_new"
    )
    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    assert len(mail.outbox) == 0


def test_same_plan_switch_does_not_set_downgrade(settings) -> None:
    """A monthly<->annual switch on the same plan is not a downgrade."""
    settings.CREEM_WEBHOOK_SECRET = "whsec_test"
    settings.CREEM_SANDBOX_WEBHOOK_SECRET = ""
    settings.CREEM_API_KEY = "sk_live"

    billing_account = _billing_account("same-plan@example.com", "studio")
    studio = Plan.objects.get(key="studio")

    body = _switch_payload(
        "same-plan@example.com", studio.creem_product_id_annual, billing_account.id, "sub_new"
    )
    resp = _signed_post(Client(), "whsec_test", body)

    assert resp.status_code == 200
    billing_account.refresh_from_db()
    assert billing_account.downgrade_detected_at is None

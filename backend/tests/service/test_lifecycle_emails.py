# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-148: send_lifecycle_email() renders the admin-editable template for a
trigger and sends via Resend's SMTP relay, logging every real send. Fails
safe (no exception, just a no-op) when no enabled template exists."""
import pytest
from django.core import mail

from payglue_backend.authn.lifecycle_emails import send_lifecycle_email
from payglue_backend.tenants.models import (
    BillingAccount,
    LifecycleEmailLog,
    LifecycleEmailTemplate,
    Plan,
    UserProfile,
)


pytestmark = pytest.mark.django_db


def _billing_account(email: str, plan_key: str = "solo") -> BillingAccount:
    plan = Plan.objects.get(key=plan_key)
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    return BillingAccount.objects.create(owner=owner, plan=plan)


def test_sends_and_logs_when_template_enabled() -> None:
    account = _billing_account("downgrader@example.com")
    LifecycleEmailTemplate.objects.filter(trigger="downgrade").update(
        subject="Bye for now, $email", body="You're on $plan now.", enabled=True
    )

    sent = send_lifecycle_email(account, LifecycleEmailTemplate.Trigger.DOWNGRADE)

    assert sent is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Bye for now, downgrader@example.com"
    assert "Solo" in mail.outbox[0].body
    assert mail.outbox[0].to == ["downgrader@example.com"]
    assert LifecycleEmailLog.objects.filter(billing_account=account, trigger="downgrade").exists()


def test_does_not_send_when_template_disabled() -> None:
    account = _billing_account("disabled@example.com")
    LifecycleEmailTemplate.objects.filter(trigger="downgrade").update(enabled=False)

    sent = send_lifecycle_email(account, LifecycleEmailTemplate.Trigger.DOWNGRADE)

    assert sent is False
    assert len(mail.outbox) == 0
    assert not LifecycleEmailLog.objects.filter(billing_account=account).exists()


def test_does_not_send_when_no_template_exists_for_trigger() -> None:
    account = _billing_account("no-template@example.com")
    LifecycleEmailTemplate.objects.filter(trigger="scheduled_cancellation").delete()

    sent = send_lifecycle_email(account, LifecycleEmailTemplate.Trigger.SCHEDULED_CANCELLATION)

    assert sent is False
    assert len(mail.outbox) == 0


def test_unknown_placeholder_in_admin_edited_template_does_not_crash() -> None:
    account = _billing_account("typo@example.com")
    LifecycleEmailTemplate.objects.filter(trigger="downgrade").update(
        subject="Hi $emial", body="Plan: $plna", enabled=True  # typo'd placeholders, on purpose
    )

    sent = send_lifecycle_email(account, LifecycleEmailTemplate.Trigger.DOWNGRADE)

    assert sent is True
    assert mail.outbox[0].subject == "Hi $emial"
    assert mail.outbox[0].body == "Plan: $plna"

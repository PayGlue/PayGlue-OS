# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-148: the send_lifecycle_emails management command polls Creem (via
the same already-live-verified _creem_subscription_for_switch helper used
by the Plans/Billing pages) instead of listening for an unverified
subscription.* webhook, and detects transitions by diffing against
BillingAccount.last_known_*."""
from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.tenants.models import BillingAccount, LifecycleEmailLog, LifecycleEmailTemplate, Plan, UserProfile

# Dashboard links in emails come from PUBLIC_APP_BASE_URL since PG-238. Without
# it app_url() returns empty, which is the correct behaviour for an install
# that has not been told where its dashboard lives.
@pytest.fixture(autouse=True)
def _dashboard_address(settings):
    settings.PUBLIC_APP_BASE_URL = "https://dashboard.example.com"




pytestmark = pytest.mark.django_db


def _billing_account(email: str, **kwargs) -> BillingAccount:
    plan = Plan.objects.get(key="solo")
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    return BillingAccount.objects.create(
        owner=owner, plan=plan, creem_subscription_id="sub_123", **kwargs
    )


def test_scheduled_cancellation_detected_and_emailed(monkeypatch: pytest.MonkeyPatch) -> None:
    LifecycleEmailTemplate.objects.filter(trigger="scheduled_cancellation").update(enabled=True)
    account = _billing_account(
        "scheduled@example.com", last_known_subscription_status="active", last_known_cancel_at_period_end=False
    )
    sub = {"status": "active", "cancel_at_period_end": True}
    monkeypatch.setattr(
        "payglue_backend.tenants.views._creem_subscription_for_switch",
        lambda profile: (sub, "sk_test", "https://test-api.creem.io", True),
    )

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.last_known_cancel_at_period_end is True
    assert account.last_known_subscription_status == "active"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["scheduled@example.com"]


def test_already_scheduled_does_not_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    LifecycleEmailTemplate.objects.filter(trigger="scheduled_cancellation").update(enabled=True)
    account = _billing_account(
        "already-scheduled@example.com",
        last_known_subscription_status="active",
        last_known_cancel_at_period_end=True,
    )
    sub = {"status": "active", "cancel_at_period_end": True}
    monkeypatch.setattr(
        "payglue_backend.tenants.views._creem_subscription_for_switch",
        lambda profile: (sub, "sk_test", "https://test-api.creem.io", True),
    )

    call_command("send_lifecycle_emails")

    assert len(mail.outbox) == 0


def test_subscription_ended_detected_and_emailed(monkeypatch: pytest.MonkeyPatch) -> None:
    LifecycleEmailTemplate.objects.filter(trigger="subscription_ended").update(enabled=True)
    account = _billing_account(
        "ended@example.com", last_known_subscription_status="active", last_known_cancel_at_period_end=True
    )
    monkeypatch.setattr(
        "payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None
    )
    # PG-190: "not found" alone is no longer enough to conclude "ended" --
    # the raw status must be confirmed "canceled" first.
    monkeypatch.setattr("payglue_backend.tenants.views._creem_raw_subscription_status", lambda acc: "canceled")

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.last_known_subscription_status == ""
    assert account.last_known_cancel_at_period_end is False
    assert account.cancellation_detected_at is not None
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ended@example.com"]


def test_never_had_active_subscription_does_not_send_ended_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards against a false positive for an account that's never actually
    been observed active/trialing yet (e.g. first poll before the checkout
    webhook has run) -- nothing "ended" if it never started."""
    LifecycleEmailTemplate.objects.filter(trigger="subscription_ended").update(enabled=True)
    _billing_account("never-active@example.com", last_known_subscription_status="")
    monkeypatch.setattr(
        "payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None
    )

    call_command("send_lifecycle_emails")

    assert len(mail.outbox) == 0


def test_dry_run_does_not_send_or_write(monkeypatch: pytest.MonkeyPatch) -> None:
    LifecycleEmailTemplate.objects.filter(trigger="scheduled_cancellation").update(enabled=True)
    account = _billing_account(
        "dryrun@example.com", last_known_subscription_status="active", last_known_cancel_at_period_end=False
    )
    sub = {"status": "active", "cancel_at_period_end": True}
    monkeypatch.setattr(
        "payglue_backend.tenants.views._creem_subscription_for_switch",
        lambda profile: (sub, "sk_test", "https://test-api.creem.io", True),
    )

    call_command("send_lifecycle_emails", "--dry-run")

    account.refresh_from_db()
    assert account.last_known_cancel_at_period_end is False
    assert len(mail.outbox) == 0


def test_no_change_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    LifecycleEmailTemplate.objects.filter(
        trigger__in=["scheduled_cancellation", "subscription_ended"]
    ).update(enabled=True)
    _billing_account(
        "steady@example.com", last_known_subscription_status="active", last_known_cancel_at_period_end=False
    )
    sub = {"status": "active", "cancel_at_period_end": False}
    monkeypatch.setattr(
        "payglue_backend.tenants.views._creem_subscription_for_switch",
        lambda profile: (sub, "sk_test", "https://test-api.creem.io", True),
    )

    call_command("send_lifecycle_emails")

    assert len(mail.outbox) == 0


def test_account_without_subscription_id_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = Plan.objects.get(key="solo")
    owner = UserProfile.objects.create(firebase_uid="uid-nosub", email="nosub@example.com")
    BillingAccount.objects.create(owner=owner, plan=plan)  # no creem_subscription_id

    called = []
    monkeypatch.setattr(
        "payglue_backend.tenants.views._creem_subscription_for_switch",
        lambda profile: called.append(profile) or None,
    )

    call_command("send_lifecycle_emails")

    assert called == []


# PG-190: confirmed cancellation (raw status "canceled") vs. an ambiguous
# Creem status (past_due/unpaid/paused/fetch failure) that only André can
# resolve by checking Creem directly.


def test_confirmed_cancellation_starts_deletion_grace_period(monkeypatch: pytest.MonkeyPatch) -> None:
    LifecycleEmailTemplate.objects.filter(trigger="subscription_ended").update(enabled=True)
    account = _billing_account(
        "canceled@example.com", last_known_subscription_status="active", last_known_cancel_at_period_end=False
    )
    monkeypatch.setattr("payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None)
    monkeypatch.setattr("payglue_backend.tenants.views._creem_raw_subscription_status", lambda acc: "canceled")

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.cancellation_detected_at is not None
    assert account.needs_admin_review is False
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["canceled@example.com"]


def test_ambiguous_status_flags_for_admin_review_and_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "pastdue@example.com", last_known_subscription_status="active", last_known_cancel_at_period_end=False
    )
    monkeypatch.setattr("payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None)
    monkeypatch.setattr("payglue_backend.tenants.views._creem_raw_subscription_status", lambda acc: "past_due")
    notified = []
    monkeypatch.setattr(
        "payglue_backend.tenants.management.commands.send_lifecycle_emails.notify_admin_review_needed",
        lambda acc, reason: notified.append((acc.pk, reason)),
    )

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.needs_admin_review is True
    assert account.admin_review_reason == "past_due"
    assert account.cancellation_detected_at is None
    assert len(mail.outbox) == 0
    assert notified == [(account.pk, "past_due")]


def test_raw_status_fetch_failure_treated_as_ambiguous_not_canceled(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "fetchfail@example.com", last_known_subscription_status="active", last_known_cancel_at_period_end=False
    )
    monkeypatch.setattr("payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None)
    monkeypatch.setattr("payglue_backend.tenants.views._creem_raw_subscription_status", lambda acc: None)
    notified = []
    monkeypatch.setattr(
        "payglue_backend.tenants.management.commands.send_lifecycle_emails.notify_admin_review_needed",
        lambda acc, reason: notified.append(reason),
    )

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.needs_admin_review is True
    assert account.admin_review_reason == "fetch_failed"
    assert account.cancellation_detected_at is None
    assert notified == ["fetch_failed"]


def test_already_flagged_account_does_not_renotify(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "already-flagged@example.com",
        last_known_subscription_status="active",
        last_known_cancel_at_period_end=False,
        needs_admin_review=True,
        admin_review_reason="past_due",
    )
    monkeypatch.setattr("payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None)
    monkeypatch.setattr("payglue_backend.tenants.views._creem_raw_subscription_status", lambda acc: "past_due")
    notified = []
    monkeypatch.setattr(
        "payglue_backend.tenants.management.commands.send_lifecycle_emails.notify_admin_review_needed",
        lambda acc, reason: notified.append(reason),
    )

    call_command("send_lifecycle_emails")

    assert notified == []


def test_review_flag_clears_once_status_resolves_to_canceled(monkeypatch: pytest.MonkeyPatch) -> None:
    LifecycleEmailTemplate.objects.filter(trigger="subscription_ended").update(enabled=True)
    account = _billing_account(
        "resolved-to-canceled@example.com",
        last_known_subscription_status="active",
        last_known_cancel_at_period_end=False,
        needs_admin_review=True,
        admin_review_reason="past_due",
    )
    monkeypatch.setattr("payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None)
    monkeypatch.setattr("payglue_backend.tenants.views._creem_raw_subscription_status", lambda acc: "canceled")

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.needs_admin_review is False
    assert account.admin_review_reason == ""
    assert account.cancellation_detected_at is not None


def test_subscription_active_again_self_heals_review_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "recovered@example.com",
        last_known_subscription_status="",
        last_known_cancel_at_period_end=False,
        needs_admin_review=True,
        admin_review_reason="past_due",
    )
    sub = {"status": "active", "cancel_at_period_end": False}
    monkeypatch.setattr(
        "payglue_backend.tenants.views._creem_subscription_for_switch",
        lambda profile: (sub, "sk_test", "https://test-api.creem.io", True),
    )

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.needs_admin_review is False
    assert account.admin_review_reason == ""


def test_resubscribing_during_grace_period_clears_deletion_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "resubscribed@example.com",
        last_known_subscription_status="",
        last_known_cancel_at_period_end=False,
        cancellation_detected_at=timezone.now(),
    )
    sub = {"status": "active", "cancel_at_period_end": False}
    monkeypatch.setattr(
        "payglue_backend.tenants.views._creem_subscription_for_switch",
        lambda profile: (sub, "sk_test", "https://test-api.creem.io", True),
    )

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.cancellation_detected_at is None


def test_dry_run_does_not_set_cancellation_or_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "dryrun-cancel@example.com", last_known_subscription_status="active", last_known_cancel_at_period_end=False
    )
    monkeypatch.setattr("payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None)
    monkeypatch.setattr("payglue_backend.tenants.views._creem_raw_subscription_status", lambda acc: "canceled")

    call_command("send_lifecycle_emails", "--dry-run")

    account.refresh_from_db()
    assert account.cancellation_detected_at is None
    assert len(mail.outbox) == 0


# PG-190: day-15 / day-29 reminders during the 30-day deletion grace period.
# The day-1 notice is SUBSCRIPTION_ENDED itself (covered above), no separate
# trigger for that one.


def test_day15_reminder_sent_once(monkeypatch: pytest.MonkeyPatch) -> None:
    LifecycleEmailTemplate.objects.filter(trigger="cancellation_reminder_15d").update(enabled=True)
    account = _billing_account(
        "day15@example.com",
        last_known_subscription_status="",
        cancellation_detected_at=timezone.now() - timedelta(days=15),
    )
    monkeypatch.setattr("payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None)

    call_command("send_lifecycle_emails")

    assert LifecycleEmailLog.objects.filter(billing_account=account, trigger="cancellation_reminder_15d").exists()
    assert len(mail.outbox) == 1

    mail.outbox.clear()
    call_command("send_lifecycle_emails")
    assert len(mail.outbox) == 0


def test_day29_sends_final_warning_not_day15_reminder(monkeypatch: pytest.MonkeyPatch) -> None:
    LifecycleEmailTemplate.objects.filter(
        trigger__in=["cancellation_reminder_15d", "cancellation_final_warning"]
    ).update(enabled=True)
    account = _billing_account(
        "day29@example.com",
        last_known_subscription_status="",
        cancellation_detected_at=timezone.now() - timedelta(days=29),
    )
    monkeypatch.setattr("payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None)

    call_command("send_lifecycle_emails")

    assert LifecycleEmailLog.objects.filter(billing_account=account, trigger="cancellation_final_warning").exists()
    assert not LifecycleEmailLog.objects.filter(billing_account=account, trigger="cancellation_reminder_15d").exists()


def test_needs_admin_review_accounts_excluded_from_reminders(monkeypatch: pytest.MonkeyPatch) -> None:
    LifecycleEmailTemplate.objects.filter(trigger="cancellation_reminder_15d").update(enabled=True)
    account = _billing_account(
        "review-and-cancel@example.com",
        last_known_subscription_status="",
        cancellation_detected_at=timezone.now() - timedelta(days=15),
        needs_admin_review=True,
        admin_review_reason="past_due",
    )
    monkeypatch.setattr("payglue_backend.tenants.views._creem_subscription_for_switch", lambda profile: None)

    call_command("send_lifecycle_emails")

    assert not LifecycleEmailLog.objects.filter(billing_account=account, trigger="cancellation_reminder_15d").exists()


def test_send_test_lifecycle_email_renders_dummy_values_and_never_logs() -> None:
    """PG-191: the admin 'send test to me' path renders placeholders with dummy
    values, prefixes [Test], sends to the given address, and never writes a
    LifecycleEmailLog (that audit trail is for real customer sends only)."""
    from payglue_backend.authn.lifecycle_emails import send_test_lifecycle_email

    template = LifecycleEmailTemplate.objects.get(trigger="scheduled_cancellation")
    template.subject = "Hi $email on $plan"
    template.body = "Ghost $tenant at $url"
    template.save()

    ok = send_test_lifecycle_email(template, "me@example.com")

    assert ok
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["me@example.com"]
    assert mail.outbox[0].subject == "[Test] Hi me@example.com on Studio"
    assert "Ghost your-publication at https://dashboard.example.com" in mail.outbox[0].body
    assert LifecycleEmailLog.objects.count() == 0

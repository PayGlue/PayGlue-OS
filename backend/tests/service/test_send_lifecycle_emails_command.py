# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-148 / PG-298: send_lifecycle_emails polls Creem and walks a lapsing
subscription through three phases (see tenants/lapse.py). The Creem lookup
is stubbed at lapse.latest_creem_subscription_for_account, the one seam the
command uses; everything below it is exercised by the views tests."""
from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from payglue_backend.tenants.models import (
    BillingAccount,
    LifecycleEmailLog,
    LifecycleEmailTemplate,
    Plan,
    Tenant,
    UserProfile,
)

# Dashboard links in emails come from PUBLIC_APP_BASE_URL since PG-238. Without
# it app_url() returns empty, which is the correct behaviour for an install
# that has not been told where its dashboard lives.
@pytest.fixture(autouse=True)
def _dashboard_address(settings):
    settings.PUBLIC_APP_BASE_URL = "https://dashboard.example.com"
    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"


pytestmark = pytest.mark.django_db

LOOKUP = "payglue_backend.tenants.lapse.latest_creem_subscription_for_account"


def _billing_account(email: str, **kwargs) -> BillingAccount:
    plan = Plan.objects.get(key="solo")
    owner = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    kwargs.setdefault("creem_subscription_id", "sub_123")
    return BillingAccount.objects.create(owner=owner, plan=plan, **kwargs)


def _creem_says(monkeypatch: pytest.MonkeyPatch, sub: dict | None) -> None:
    monkeypatch.setattr(
        LOOKUP,
        lambda account: None if sub is None else (sub, "sk_test", "https://test-api.creem.io", True),
    )


def _enable(*triggers: str) -> None:
    LifecycleEmailTemplate.objects.filter(trigger__in=triggers).update(enabled=True)


# --------------------------------------------------------------- alive


def test_scheduled_cancellation_detected_and_emailed(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("scheduled_cancellation")
    account = _billing_account(
        "scheduled@example.com", last_known_subscription_status="active", last_known_cancel_at_period_end=False
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "active", "cancel_at_period_end": True})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.last_known_cancel_at_period_end is True
    assert account.last_known_subscription_status == "active"
    assert [m.to for m in mail.outbox] == [["scheduled@example.com"]]


def test_already_scheduled_does_not_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("scheduled_cancellation")
    _billing_account(
        "already-scheduled@example.com",
        last_known_subscription_status="active",
        last_known_cancel_at_period_end=True,
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "active", "cancel_at_period_end": True})

    call_command("send_lifecycle_emails")

    assert len(mail.outbox) == 0


def test_no_change_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("scheduled_cancellation", "subscription_ended", "payment_failed")
    account = _billing_account("steady@example.com", last_known_subscription_status="active")
    _creem_says(monkeypatch, {"id": "sub_123", "status": "active", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.payment_failed_detected_at is None
    assert account.cancellation_detected_at is None
    assert len(mail.outbox) == 0


def test_poll_stores_ids_found_by_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """The PG-298 bug in one test: an account without a stored id used to be
    skipped entirely. Now it is looked up and the ids are written back."""
    account = _billing_account("first-buy@example.com", creem_subscription_id="", creem_customer_id="")
    _creem_says(
        monkeypatch,
        {"id": "sub_found", "customer": {"id": "cust_found"}, "status": "active", "cancel_at_period_end": False},
    )

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.creem_subscription_id == "sub_found"
    assert account.creem_customer_id == "cust_found"
    assert account.last_known_subscription_status == "active"


def test_testers_are_not_polled(monkeypatch: pytest.MonkeyPatch) -> None:
    _billing_account("tester@example.com", is_tester=True, creem_subscription_id="")
    calls = []
    monkeypatch.setattr(LOOKUP, lambda account: calls.append(account) or None)

    call_command("send_lifecycle_emails")

    assert calls == []


# ------------------------------------------------------------- phase 1


def test_past_due_starts_phase_one_and_emails_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("payment_failed")
    account = _billing_account("retry@example.com", last_known_subscription_status="active")
    _creem_says(monkeypatch, {"id": "sub_123", "status": "past_due", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")
    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.payment_failed_detected_at is not None
    assert account.cancellation_detected_at is None
    assert account.needs_admin_review is False
    assert account.last_known_subscription_status == "past_due"
    assert [m.to for m in mail.outbox] == [["retry@example.com"]]


def test_past_due_reminder_after_three_days(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("payment_failed", "payment_failed_reminder")
    account = _billing_account(
        "retry-reminder@example.com",
        last_known_subscription_status="past_due",
        payment_failed_detected_at=timezone.now() - timedelta(days=3, hours=1),
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "past_due", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")
    call_command("send_lifecycle_emails")

    triggers = list(LifecycleEmailLog.objects.filter(billing_account=account).values_list("trigger", flat=True))
    assert triggers == ["payment_failed_reminder"]


def test_past_due_reminder_not_before_three_days(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("payment_failed_reminder")
    _billing_account(
        "retry-early@example.com",
        last_known_subscription_status="past_due",
        payment_failed_detected_at=timezone.now() - timedelta(days=1),
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "past_due", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    assert len(mail.outbox) == 0


def test_card_retry_succeeds_clears_phase_one(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "healed@example.com",
        last_known_subscription_status="past_due",
        payment_failed_detected_at=timezone.now() - timedelta(days=2),
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "active", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.payment_failed_detected_at is None
    assert account.last_known_subscription_status == "active"


# ------------------------------------------------------------- phase 2


@pytest.mark.parametrize("ended_status", ["unpaid", "canceled", "paused", "expired"])
def test_ended_status_starts_grace_period(monkeypatch: pytest.MonkeyPatch, ended_status: str) -> None:
    _enable("subscription_ended")
    account = _billing_account(f"ended-{ended_status}@example.com", last_known_subscription_status="active")
    _creem_says(monkeypatch, {"id": "sub_123", "status": ended_status, "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.cancellation_detected_at is not None
    assert account.needs_admin_review is False
    assert account.last_known_subscription_status == ended_status
    assert [m.to for m in mail.outbox] == [[f"ended-{ended_status}@example.com"]]


def test_phase_one_moves_to_phase_two_when_creem_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """Maximus: past_due for a week, then Creem stops retrying. The account
    was last seen past_due, not active, and must still enter the grace
    period because phase 1 proves there was a live subscription."""
    _enable("subscription_ended")
    account = _billing_account(
        "maximus@example.com",
        last_known_subscription_status="past_due",
        payment_failed_detected_at=timezone.now() - timedelta(days=7),
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "unpaid", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.cancellation_detected_at is not None
    assert account.payment_failed_detected_at is None
    assert len(mail.outbox) == 1


def test_past_due_for_two_weeks_counts_as_ended(monkeypatch: pytest.MonkeyPatch) -> None:
    """Found live: Creem kept reporting past_due days after its last retry.
    Phase 1 has a cap so the account does not sit on full access forever."""
    _enable("subscription_ended")
    account = _billing_account(
        "stuck@example.com",
        last_known_subscription_status="past_due",
        payment_failed_detected_at=timezone.now() - timedelta(days=14, hours=1),
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "past_due", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.cancellation_detected_at is not None
    assert account.payment_failed_detected_at is None
    assert [m.to for m in mail.outbox] == [["stuck@example.com"]]


def test_past_due_under_two_weeks_stays_in_phase_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("subscription_ended")
    account = _billing_account(
        "not-stuck@example.com",
        last_known_subscription_status="past_due",
        payment_failed_detected_at=timezone.now() - timedelta(days=13),
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "past_due", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.cancellation_detected_at is None
    assert len(mail.outbox) == 0


def test_grace_period_is_not_restarted_on_later_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("subscription_ended")
    started = timezone.now() - timedelta(days=10)
    account = _billing_account(
        "in-grace@example.com", last_known_subscription_status="canceled", cancellation_detected_at=started
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "canceled", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.cancellation_detected_at == started
    assert len(mail.outbox) == 0


def test_never_seen_alive_does_not_start_grace_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """An old, dead subscription of somebody who is comped today. Recording
    the status is fine; a grace period for it would be invented."""
    _enable("subscription_ended")
    account = _billing_account("comped@example.com", last_known_subscription_status="", creem_subscription_id="")
    _creem_says(monkeypatch, {"id": "sub_old", "status": "canceled", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.cancellation_detected_at is None
    assert account.creem_subscription_id == "sub_old"
    assert account.last_known_subscription_status == "canceled"
    assert len(mail.outbox) == 0


def test_resubscribing_during_grace_period_clears_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "back@example.com",
        last_known_subscription_status="canceled",
        cancellation_detected_at=timezone.now() - timedelta(days=5),
    )
    _creem_says(monkeypatch, {"id": "sub_new", "status": "active", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.cancellation_detected_at is None
    assert account.creem_subscription_id == "sub_new"


def test_day15_reminder_sent_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("cancellation_reminder_15d")
    account = _billing_account(
        "day15@example.com",
        last_known_subscription_status="canceled",
        cancellation_detected_at=timezone.now() - timedelta(days=16),
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "canceled", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")
    call_command("send_lifecycle_emails")

    assert LifecycleEmailLog.objects.filter(billing_account=account, trigger="cancellation_reminder_15d").count() == 1


def test_day29_sends_final_warning_not_day15_reminder(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("cancellation_reminder_15d", "cancellation_final_warning")
    account = _billing_account(
        "day29@example.com",
        last_known_subscription_status="canceled",
        cancellation_detected_at=timezone.now() - timedelta(days=29, hours=1),
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "canceled", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    triggers = set(LifecycleEmailLog.objects.filter(billing_account=account).values_list("trigger", flat=True))
    assert triggers == {"cancellation_final_warning"}


def test_reminder_repeats_for_a_second_lapse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once per phase, not once per account: a customer who lapsed last year
    and lapses again gets the day-15 reminder again."""
    _enable("cancellation_reminder_15d")
    account = _billing_account(
        "twice@example.com",
        last_known_subscription_status="canceled",
        cancellation_detected_at=timezone.now() - timedelta(days=16),
    )
    old = LifecycleEmailLog.objects.create(billing_account=account, trigger="cancellation_reminder_15d")
    LifecycleEmailLog.objects.filter(pk=old.pk).update(sent_at=timezone.now() - timedelta(days=200))
    _creem_says(monkeypatch, {"id": "sub_123", "status": "canceled", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    assert LifecycleEmailLog.objects.filter(billing_account=account, trigger="cancellation_reminder_15d").count() == 2


# ------------------------------------------------------------- phase 3


# ------------------------------------------------- deletion notice (PG-303)


def _paused_for(days: int, email: str = "paused@example.com") -> BillingAccount:
    return _billing_account(
        email,
        last_known_subscription_status="canceled",
        cancellation_detected_at=timezone.now() - timedelta(days=days + 30),
        lapsed_at=timezone.now() - timedelta(days=days),
    )


def test_deletion_notice_a_week_before_deletion_carries_the_date(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("deletion_notice")
    account = _paused_for(83)
    _creem_says(monkeypatch, {"id": "sub_123", "status": "canceled"})

    call_command("send_lifecycle_emails")
    call_command("send_lifecycle_emails")

    assert [m.to for m in mail.outbox] == [["paused@example.com"]]
    expected = (account.lapsed_at + timedelta(days=90)).strftime("%-d %B %Y")
    assert expected in mail.outbox[0].subject
    assert expected in mail.outbox[0].body
    assert LifecycleEmailLog.objects.filter(billing_account=account, trigger="deletion_notice").count() == 1


def test_deletion_notice_not_before_day_83(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("deletion_notice")
    _paused_for(82)
    _creem_says(monkeypatch, {"id": "sub_123", "status": "canceled"})

    call_command("send_lifecycle_emails")

    assert mail.outbox == []


def test_paying_again_after_the_notice_stops_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("deletion_notice")
    account = _paused_for(84)
    tenant = Tenant.objects.create(
        slug="back-tenant", schema_name="back_tenant", billing_account=account, status=Tenant.Status.PAUSED
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "active"})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    tenant.refresh_from_db()
    assert account.lapsed_at is None
    assert tenant.status == Tenant.Status.ACTIVE
    assert mail.outbox == []


def test_lapsed_account_paying_again_resumes_tenants(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "resume@example.com",
        last_known_subscription_status="canceled",
        cancellation_detected_at=timezone.now() - timedelta(days=40),
        lapsed_at=timezone.now() - timedelta(days=5),
    )
    tenant = Tenant.objects.create(
        slug="resume-tenant", schema_name="resume_tenant", billing_account=account, status=Tenant.Status.PAUSED
    )
    _creem_says(monkeypatch, {"id": "sub_new", "status": "active", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    tenant.refresh_from_db()
    assert account.lapsed_at is None
    assert account.cancellation_detected_at is None
    assert tenant.status == Tenant.Status.ACTIVE


# --------------------------------------------------------- unclear cases


def test_stored_id_creem_does_not_answer_flags_for_review(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account("gone@example.com", last_known_subscription_status="active")
    _creem_says(monkeypatch, None)

    call_command("send_lifecycle_emails")
    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.needs_admin_review is True
    assert account.admin_review_reason == "not_found"
    assert account.cancellation_detected_at is None
    # One operator mail, not one per poll.
    assert [m.to for m in mail.outbox] == [["ops@example.com"]]


def test_unknown_status_flags_for_review(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account("weird@example.com", last_known_subscription_status="active")
    _creem_says(monkeypatch, {"id": "sub_123", "status": "incomplete", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.needs_admin_review is True
    assert account.admin_review_reason == "incomplete"
    assert account.last_known_subscription_status == "incomplete"


def test_no_subscription_at_creem_and_none_expected_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account("manual@example.com", creem_subscription_id="", last_known_subscription_status="")
    _creem_says(monkeypatch, None)

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.needs_admin_review is False
    assert len(mail.outbox) == 0


def test_review_flag_self_heals_when_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    account = _billing_account(
        "healed-review@example.com",
        last_known_subscription_status="",
        needs_admin_review=True,
        admin_review_reason="not_found",
    )
    _creem_says(monkeypatch, {"id": "sub_123", "status": "active", "cancel_at_period_end": False})

    call_command("send_lifecycle_emails")

    account.refresh_from_db()
    assert account.needs_admin_review is False
    assert account.admin_review_reason == ""


# ------------------------------------------------------------- dry run


def test_dry_run_does_not_send_or_write(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("subscription_ended")
    account = _billing_account("dry@example.com", last_known_subscription_status="active", creem_customer_id="")
    _creem_says(
        monkeypatch,
        {"id": "sub_123", "customer": "cust_x", "status": "canceled", "cancel_at_period_end": False},
    )

    call_command("send_lifecycle_emails", "--dry-run")

    account.refresh_from_db()
    assert account.cancellation_detected_at is None
    assert account.creem_customer_id == ""
    assert account.last_known_subscription_status == "active"
    assert len(mail.outbox) == 0


def test_needs_admin_review_accounts_excluded_from_reminders(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable("cancellation_reminder_15d")
    account = _billing_account(
        "review-and-cancel@example.com",
        last_known_subscription_status="",
        cancellation_detected_at=timezone.now() - timedelta(days=15),
        needs_admin_review=True,
        admin_review_reason="not_found",
    )
    _creem_says(monkeypatch, None)

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

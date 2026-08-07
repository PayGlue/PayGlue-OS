# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The two-mail onboarding sequence.

Built in-house rather than in an email tool for one reason worth restating:
the day-15 mail must skip anyone who has cancelled, and that state already
lives here because send_lifecycle_emails polls Creem for it daily. An external
tool would have needed PayGlue to push it a cancellation signal it does not
otherwise send.
"""
from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone

from payglue_backend.authn.lifecycle_emails import send_lifecycle_email
from payglue_backend.tenants.models import (
    BillingAccount,
    LifecycleEmailLog,
    LifecycleEmailTemplate,
    Plan,
    UserProfile,
)

pytestmark = pytest.mark.django_db

WELCOME = LifecycleEmailTemplate.Trigger.ONBOARDING_WELCOME
DAY15 = LifecycleEmailTemplate.Trigger.ONBOARDING_DAY15


def _account(suffix: str = "a", *, age_days: int = 0) -> BillingAccount:
    profile = UserProfile.objects.create(
        firebase_uid=f"uid-onb-{suffix}", email=f"onb-{suffix}@example.com"
    )
    account = BillingAccount.objects.create(
        owner=profile, plan=Plan.objects.get(key="founding")
    )
    if age_days:
        # auto_now_add ignores an assigned value, so age it with an update().
        BillingAccount.objects.filter(id=account.id).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )
        account.refresh_from_db()
    return account


@pytest.fixture(autouse=True)
def _templates_switched_on() -> None:
    """Every test below is about the sending logic, not about the default.

    The seeded rows are off (see the test right underneath), so without this
    each of them would pass for the wrong reason: nothing sent, nothing to get
    wrong.
    """
    LifecycleEmailTemplate.objects.filter(trigger__in=(WELCOME, DAY15)).update(enabled=True)


def test_welcome_sends_once_and_only_once() -> None:
    account = _account()
    mail.outbox.clear()

    assert send_lifecycle_email(account, WELCOME)
    assert len(mail.outbox) == 1
    assert "Welcome to PayGlue" in mail.outbox[0].subject

    # The partial constraint, not a caller-side check, is what stops the second.
    with pytest.raises(IntegrityError), transaction.atomic():
        LifecycleEmailLog.objects.create(billing_account=account, trigger=WELCOME)


def test_repeating_triggers_are_not_caught_by_that_constraint() -> None:
    """A blanket unique constraint would have broken these: ghost delivery
    alerts fire per incident, not once per account."""
    account = _account()
    for _ in range(2):
        LifecycleEmailLog.objects.create(
            billing_account=account,
            trigger=LifecycleEmailTemplate.Trigger.GHOST_DELIVERY_FAILING,
        )
    assert LifecycleEmailLog.objects.filter(billing_account=account).count() == 2


def test_day15_reaches_an_account_that_is_old_enough_and_still_here() -> None:
    account = _account("old", age_days=16)
    mail.outbox.clear()

    call_command("send_lifecycle_emails")

    assert [m.to for m in mail.outbox] == [["onb-old@example.com"]]
    assert LifecycleEmailLog.objects.filter(billing_account=account, trigger=DAY15).exists()


def test_day15_skips_an_account_that_is_too_young() -> None:
    _account("young", age_days=3)
    mail.outbox.clear()

    call_command("send_lifecycle_emails")

    assert mail.outbox == []


def test_day15_skips_someone_who_already_cancelled() -> None:
    """The whole reason this lives in the backend: asking "are they still a
    customer" needs the cancellation state, which is right here."""
    account = _account("gone", age_days=20)
    account.cancellation_detected_at = timezone.now()
    account.save(update_fields=["cancellation_detected_at"])
    mail.outbox.clear()

    call_command("send_lifecycle_emails")

    assert mail.outbox == []
    assert not LifecycleEmailLog.objects.filter(trigger=DAY15).exists()


def test_day15_does_not_repeat_on_the_next_run() -> None:
    _account("twice", age_days=40)

    call_command("send_lifecycle_emails")
    mail.outbox.clear()
    call_command("send_lifecycle_emails")

    assert mail.outbox == []


def test_day15_covers_testers_too() -> None:
    """Comped and tester accounts are onboarding as much as paying ones, and
    they have no Creem subscription to poll."""
    account = _account("tester", age_days=20)
    account.is_tester = True
    account.save(update_fields=["is_tester"])
    mail.outbox.clear()

    call_command("send_lifecycle_emails")

    assert [m.to for m in mail.outbox] == [["onb-tester@example.com"]]


def test_dry_run_sends_nothing() -> None:
    _account("dry", age_days=20)
    mail.outbox.clear()

    call_command("send_lifecycle_emails", "--dry-run")

    assert mail.outbox == []
    assert not LifecycleEmailLog.objects.filter(trigger=DAY15).exists()

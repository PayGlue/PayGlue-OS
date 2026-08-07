# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-183: PayGlue-issued tester license codes. Redeemed at signup without a
Creem purchase; grant the code's plan as a "Tester" for a fixed window, then the
standard 30-day deletion grace kicks in."""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from payglue_backend.tenants.models import (
    BillingAccount,
    InvitationGrant,
    LicenseCode,
    Plan,
    UserProfile,
)
from payglue_backend.tenants.serializers import TenantCreateSerializer

pytestmark = pytest.mark.django_db

_VALIDATE_URL = "/api/v1/auth/access/validate"


def _code(*, plan_key: str = "studio", access_days: int = 7, max_activations=None, is_active=True) -> LicenseCode:
    return LicenseCode.objects.create(
        plan=Plan.objects.get(key=plan_key),
        access_days=access_days,
        max_activations=max_activations,
        is_active=is_active,
    )


def _validate(email: str, key: str):
    return Client().post(
        _VALIDATE_URL, data={"email": email, "license_key": key}, content_type="application/json"
    )


def test_payglue_code_redeems_email_agnostic_and_counts_activation() -> None:
    code = _code(max_activations=5)
    # Case-insensitive: the stored code is upper-case, the user pastes lower-case.
    resp = _validate("whoever@example.com", code.code.lower())

    assert resp.status_code == 200
    grant = InvitationGrant.objects.get(email="whoever@example.com")
    assert grant.source == InvitationGrant.Source.PAYGLUE_LICENSE
    assert grant.license_code_id == code.id
    code.refresh_from_db()
    assert code.activation_count == 1


def test_payglue_code_respects_max_activations() -> None:
    code = _code(max_activations=1)
    assert _validate("first@example.com", code.code).status_code == 200

    resp = _validate("second@example.com", code.code)
    assert resp.status_code in (400, 409)
    code.refresh_from_db()
    assert code.activation_count == 1


def test_payglue_code_unlimited_when_max_blank() -> None:
    code = _code(max_activations=None)
    assert _validate("a@example.com", code.code).status_code == 200
    assert _validate("b@example.com", code.code).status_code == 200
    code.refresh_from_db()
    assert code.activation_count == 2


def test_inactive_or_unknown_code_rejected() -> None:
    inactive = _code(is_active=False)
    assert _validate("a@example.com", inactive.code).status_code == 400
    assert _validate("a@example.com", "PAYGLUE-DOESNOTEXIST").status_code == 400


def test_first_publication_provisions_tester_billing_with_expiry() -> None:
    code = _code(plan_key="studio", access_days=7)
    profile = UserProfile.objects.create(firebase_uid="uid-tester", email="tester@example.com")
    InvitationGrant.objects.create(
        email="tester@example.com",
        source=InvitationGrant.Source.PAYGLUE_LICENSE,
        license_code=code,
    )

    serializer = TenantCreateSerializer(
        data={"slug": "tester-pub"}, context={"user_profile": profile}
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    account = BillingAccount.objects.get(owner=profile)
    assert account.is_tester is True
    assert account.plan.key == "studio"
    assert account.tester_access_expires_at is not None
    assert account.license_code_id == code.id


def test_never_expiring_code_leaves_no_expiry() -> None:
    code = _code(access_days=0)
    profile = UserProfile.objects.create(firebase_uid="uid-forever", email="forever@example.com")
    InvitationGrant.objects.create(
        email="forever@example.com",
        source=InvitationGrant.Source.PAYGLUE_LICENSE,
        license_code=code,
    )

    serializer = TenantCreateSerializer(
        data={"slug": "forever-pub"}, context={"user_profile": profile}
    )
    serializer.is_valid(raise_exception=True)
    serializer.save()

    account = BillingAccount.objects.get(owner=profile)
    assert account.is_tester is True
    assert account.tester_access_expires_at is None


def _tester_account(email: str, expires_at) -> BillingAccount:
    profile = UserProfile.objects.create(firebase_uid=f"uid-{email}", email=email)
    return BillingAccount.objects.create(
        owner=profile,
        plan=Plan.objects.get(key="studio"),
        is_tester=True,
        tester_access_expires_at=expires_at,
    )


def test_expire_tester_access_starts_grace_for_lapsed_window() -> None:
    account = _tester_account("lapsed@example.com", timezone.now() - timedelta(days=1))

    call_command("expire_tester_access")

    account.refresh_from_db()
    assert account.cancellation_detected_at is not None


def test_expire_tester_access_ignores_never_expiry_and_future_windows() -> None:
    never = _tester_account("never@example.com", None)
    future = _tester_account("future@example.com", timezone.now() + timedelta(days=3))

    call_command("expire_tester_access")

    never.refresh_from_db()
    future.refresh_from_db()
    assert never.cancellation_detected_at is None
    assert future.cancellation_detected_at is None


def test_redeeming_a_code_emails_the_admin_once(mailoutbox, settings) -> None:
    """Creem purchases announce themselves; our own codes did not, so a signup
    on an invite code was invisible until somebody looked in the admin."""
    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    code = _code(max_activations=5)

    assert _validate("tester@example.com", code.code).status_code == 200

    admin_mails = [m for m in mailoutbox if "ops@example.com" in m.to]
    assert len(admin_mails) == 1
    assert code.code in admin_mails[0].subject
    body = admin_mails[0].body
    assert "tester@example.com" in body
    # The remaining-activations line is the whole point of the mail: it says
    # how much of a shared code is left without opening the admin.
    assert "4 of 5 left" in body


def test_retrying_the_same_redemption_does_not_email_again(mailoutbox, settings) -> None:
    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    code = _code(max_activations=5)

    assert _validate("tester@example.com", code.code).status_code == 200
    # Same person hits validate again (double-click, back button, retry).
    assert _validate("tester@example.com", code.code).status_code == 200

    assert len([m for m in mailoutbox if "ops@example.com" in m.to]) == 1
    code.refresh_from_db()
    assert code.activation_count == 1

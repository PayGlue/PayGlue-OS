"""The invite-gate bypass must not ship with an address baked in.

`DEV_BYPASS_EMAILS` lets a listed address create a profile without an
InvitationGrant. That is a useful shortcut for whoever runs an instance, and a
liability the moment it has a default: this settings module ships in the
open-source build, so a baked-in address would give every self-hosted install
an account that needs no invitation. Whether it is reachable then depends on
that operator's Supabase configuration, which is exactly the kind of thing we
should not be making assumptions about.

These tests pin the empty default and the behaviour behind it.
"""

import os

import pytest
from django.conf import settings
from django.test import override_settings

from payglue_backend.authn.profile_gate import (
    InviteGateError,
    resolve_profile_with_invite_gate,
)
from payglue_backend.authn.verifier import VerifiedTokenClaims
from payglue_backend.tenants.models import UserProfile

pytestmark = pytest.mark.django_db


@pytest.mark.skipif(
    bool(os.environ.get("DEV_BYPASS_EMAILS")),
    reason="DEV_BYPASS_EMAILS is set in this environment, so the default is not observable",
)
def test_shipped_default_is_empty() -> None:
    assert settings.DEV_BYPASS_EMAILS == set()


@override_settings(DEV_BYPASS_EMAILS=set())
def test_unknown_email_without_invite_is_rejected() -> None:
    claims = VerifiedTokenClaims(firebase_uid="uid-nobody", email="nobody@example.com")

    with pytest.raises(InviteGateError):
        resolve_profile_with_invite_gate(claims)

    assert not UserProfile.objects.filter(email="nobody@example.com").exists()


@override_settings(DEV_BYPASS_EMAILS={"listed@example.com"})
def test_a_listed_email_still_bypasses_when_configured() -> None:
    # The shortcut has to keep working for whoever deliberately turns it on,
    # otherwise the empty default would just be a broken feature.
    claims = VerifiedTokenClaims(firebase_uid="uid-listed", email="listed@example.com")

    profile = resolve_profile_with_invite_gate(claims)

    assert profile.email == "listed@example.com"
    assert profile.firebase_uid == "uid-listed"


@override_settings(DEV_BYPASS_EMAILS={"listed@example.com"})
def test_the_bypass_does_not_leak_to_neighbouring_addresses() -> None:
    claims = VerifiedTokenClaims(firebase_uid="uid-other", email="listed@example.com.evil.test")

    with pytest.raises(InviteGateError):
        resolve_profile_with_invite_gate(claims)

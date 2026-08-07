# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-203 step-up: the checks that make the confirmation real rather than a
dialog. Each test here maps to a way the feature could look like it works while
authorising something it should not."""
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from payglue_backend.authn import step_up
from payglue_backend.authn.step_up import (
    StepUpError,
    issue_challenge,
    require_step_up,
    verify_challenge,
)
from payglue_backend.tenants.models import StepUpChallenge, StepUpGrant, UserProfile

pytestmark = pytest.mark.django_db

DELETE = StepUpChallenge.Purpose.DELETE_ACCOUNT
TRANSFER = StepUpChallenge.Purpose.OWNER_TRANSFER


def _profile(suffix: str = "a") -> UserProfile:
    return UserProfile.objects.create(
        firebase_uid=f"uid-step-up-{suffix}", email=f"step-up-{suffix}@example.com"
    )


class _Request:
    """Minimal stand-in: require_step_up only ever reads a header."""

    def __init__(self, token: str | None = None) -> None:
        self.headers = {step_up.STEP_UP_HEADER: token} if token else {}


def _issue_email_challenge(profile: UserProfile, purpose: str) -> str:
    """Issue an email challenge and return the plaintext code.

    No verified TOTP factor, so the email branch is taken; the send itself is
    patched out because we are testing the gate, not the mail.
    """
    sent: dict[str, str] = {}

    def _capture(prof, code, purp):
        sent["code"] = code

    with mock.patch.object(step_up, "_verified_totp_factor_id", return_value=""), mock.patch.object(
        step_up, "_send_code_email", _capture
    ):
        issued = issue_challenge(profile, purpose, "jwt")
    assert issued.method == StepUpChallenge.Method.EMAIL
    return sent["code"]


def test_correct_code_issues_a_grant() -> None:
    profile = _profile()
    code = _issue_email_challenge(profile, DELETE)

    token = verify_challenge(profile, DELETE, code, "jwt")

    assert token
    assert StepUpGrant.objects.filter(user_profile=profile, purpose=DELETE).count() == 1


def test_wrong_code_is_rejected_and_burns_an_attempt() -> None:
    profile = _profile()
    _issue_email_challenge(profile, DELETE)

    with pytest.raises(StepUpError):
        verify_challenge(profile, DELETE, "000000", "jwt")

    challenge = StepUpChallenge.objects.get(user_profile=profile)
    assert challenge.attempts == 1
    assert challenge.consumed_at is None  # still usable, just one guess down
    assert not StepUpGrant.objects.exists()


def test_expired_challenge_is_rejected() -> None:
    profile = _profile()
    code = _issue_email_challenge(profile, DELETE)
    StepUpChallenge.objects.filter(user_profile=profile).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    with pytest.raises(StepUpError):
        verify_challenge(profile, DELETE, code, "jwt")
    assert not StepUpGrant.objects.exists()


def test_attempt_limit_closes_the_challenge_even_for_the_right_code() -> None:
    """Otherwise a six-digit space is walkable: guess freely, then finish."""
    profile = _profile()
    code = _issue_email_challenge(profile, DELETE)
    StepUpChallenge.objects.filter(user_profile=profile).update(
        attempts=StepUpChallenge.MAX_ATTEMPTS
    )

    with pytest.raises(StepUpError):
        verify_challenge(profile, DELETE, code, "jwt")
    assert not StepUpGrant.objects.exists()


def test_reissuing_supersedes_the_previous_code() -> None:
    """Reopening the dialog must not leave an older code live."""
    profile = _profile()
    first = _issue_email_challenge(profile, DELETE)
    second = _issue_email_challenge(profile, DELETE)
    assert first != second

    with pytest.raises(StepUpError):
        verify_challenge(profile, DELETE, first, "jwt")
    assert verify_challenge(profile, DELETE, second, "jwt")


def test_grant_is_single_use() -> None:
    """Confirming once must authorise exactly one destructive call."""
    profile = _profile()
    token = verify_challenge(profile, DELETE, _issue_email_challenge(profile, DELETE), "jwt")

    require_step_up(_Request(token), profile, DELETE)  # spends it
    with pytest.raises(StepUpError):
        require_step_up(_Request(token), profile, DELETE)


def test_grant_does_not_cross_purposes() -> None:
    """Confirming an owner transfer must never also authorise a deletion."""
    profile = _profile()
    token = verify_challenge(profile, TRANSFER, _issue_email_challenge(profile, TRANSFER), "jwt")

    with pytest.raises(StepUpError):
        require_step_up(_Request(token), profile, DELETE)


def test_grant_does_not_cross_users() -> None:
    profile = _profile("a")
    other = _profile("b")
    token = verify_challenge(profile, DELETE, _issue_email_challenge(profile, DELETE), "jwt")

    with pytest.raises(StepUpError):
        require_step_up(_Request(token), other, DELETE)


def test_expired_grant_is_refused() -> None:
    profile = _profile()
    token = verify_challenge(profile, DELETE, _issue_email_challenge(profile, DELETE), "jwt")
    StepUpGrant.objects.filter(user_profile=profile).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    with pytest.raises(StepUpError):
        require_step_up(_Request(token), profile, DELETE)


def test_missing_header_is_refused() -> None:
    """The default path for anyone calling the API directly, skipping the UI."""
    with pytest.raises(StepUpError):
        require_step_up(_Request(), _profile(), DELETE)


def test_plaintext_code_is_never_stored() -> None:
    profile = _profile()
    code = _issue_email_challenge(profile, DELETE)
    challenge = StepUpChallenge.objects.get(user_profile=profile)

    assert code not in challenge.code_hash
    assert len(challenge.code_hash) == 64


def test_totp_account_gets_no_email() -> None:
    """A verified authenticator means no mail is sent at all."""
    profile = _profile()
    with mock.patch.object(
        step_up, "_verified_totp_factor_id", return_value="factor-1"
    ), mock.patch.object(
        step_up, "_supabase_call", return_value={"id": "challenge-1"}
    ), mock.patch.object(step_up, "_send_code_email") as send:
        issued = issue_challenge(profile, DELETE, "jwt")

    assert issued.method == StepUpChallenge.Method.TOTP
    assert issued.challenge_id == "challenge-1"
    send.assert_not_called()


def test_unverified_totp_factor_does_not_count() -> None:
    """An enrolled-but-unverified factor would let an attacker register their
    own and immediately confirm with it."""
    with mock.patch.object(
        step_up,
        "_supabase_call",
        return_value={"factors": [{"id": "f1", "status": "unverified", "factor_type": "totp"}]},
    ):
        assert step_up._verified_totp_factor_id("jwt") == ""


def test_factors_are_read_from_the_user_object() -> None:
    """Regression: this shipped calling GET /factors, which GoTrue answers with
    405 (the path is POST-only, for enrolment). Step-up was dead on arrival for
    everyone, including email users, because the lookup runs before the branch.
    Pin the endpoint, since every other test here mocks straight past it."""
    seen: dict[str, str] = {}

    def _capture(method, path, user_jwt, body=None, **kwargs):
        seen["method"], seen["path"] = method, path
        return {"factors": [{"id": "f1", "status": "verified", "factor_type": "totp"}]}

    with mock.patch.object(step_up, "_supabase_call", _capture):
        assert step_up._verified_totp_factor_id("jwt") == "f1"

    assert (seen["method"], seen["path"]) == ("GET", "/user")


def test_a_4xx_while_starting_is_not_blamed_on_the_user() -> None:
    """A failure before anything is typed must read as "service unavailable",
    not "that code was not accepted" -- the latter is what hid the 405."""
    import urllib.error

    def _raise(*args, **kwargs):
        raise urllib.error.HTTPError("u", 405, "Method Not Allowed", {}, None)

    with mock.patch.object(step_up.urlrequest, "urlopen", _raise), mock.patch.object(
        step_up, "_supabase_auth_base", return_value="https://example.test/auth/v1"
    ):
        with pytest.raises(step_up.StepUpUnavailable):
            step_up._supabase_call("GET", "/user", "jwt")

        with pytest.raises(StepUpError):
            step_up._supabase_call(
                "POST", "/factors/f1/verify", "jwt", {}, bad_request_is_user_error=True
            )


def test_unknown_purpose_is_rejected() -> None:
    with pytest.raises(StepUpError):
        issue_challenge(_profile(), "something_else", "jwt")

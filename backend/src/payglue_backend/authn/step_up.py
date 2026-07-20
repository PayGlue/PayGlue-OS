# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Step-up ("sudo mode") re-confirmation for destructive actions. PG-203.

PG-203 inherited a plan from PG-182 that no longer fits: it proposed either a
password prompt or a second magic-link click. Login has since moved to OAuth,
password, and emailed OTP codes, so magic links are gone; and a password prompt
proves little once a session is already stolen, on top of assuming a password
that OAuth users never set.

What this does instead: the user stays signed in and confirms once, in an
overlay. Two proof methods, picked by what the account already has.

The TOTP path is the subtle one. Supabase holds the factor secret, so we cannot
check the six digits ourselves. The backend therefore forwards *the user's own
JWT* to Supabase's factors API and lets Supabase verify. That keeps the check
on the server: if the browser could self-certify, the overlay would be a
decoration anyone could skip by calling the API directly.

Freshness is deliberately not taken from the JWT's `aal` claim. A plain token
refresh keeps `aal2` while proving nothing happened, so trusting that claim
would have made this weakest exactly where MFA is enabled.
"""
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib import error, request as urlrequest

from django.conf import settings
from django.utils import timezone

from payglue_backend.tenants.models import (
    StepUpChallenge,
    StepUpGrant,
    UserProfile,
    _generate_step_up_code,
    _hash_step_up_secret,
)

logger = logging.getLogger(__name__)

STEP_UP_HEADER = "X-Step-Up-Token"


class StepUpError(Exception):
    """Anything that should surface to the client as a 4xx with a safe message."""


class StepUpUnavailable(Exception):
    """Supabase could not be reached. Distinct from StepUpError so the view can
    answer 503 rather than blaming the user's code."""


@dataclass(frozen=True)
class ChallengeIssued:
    method: str
    # Only set for the TOTP path, so the client can hand it back on verify.
    challenge_id: str = ""


def _supabase_auth_base() -> str:
    base = getattr(settings, "SUPABASE_URL", "") or ""
    if not base:
        raise StepUpUnavailable("Supabase URL is not configured.")
    return f"{base.rstrip('/')}/auth/v1"


def _supabase_call(
    method: str,
    path: str,
    user_jwt: str,
    body: dict | None = None,
    *,
    bad_request_is_user_error: bool = False,
) -> dict:
    """Call Supabase's auth API as the user, using their own bearer token.

    The publishable key goes in `apikey` because Supabase requires it on every
    auth call. It identifies the project and authorises nothing; authorisation
    comes from the user's JWT, so this cannot reach anybody else's factors.
    """
    url = f"{_supabase_auth_base()}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urlrequest.Request(
        url=url,
        data=data,
        headers={
            "Authorization": f"Bearer {user_jwt}",
            "apikey": getattr(settings, "SUPABASE_PUBLISHABLE_KEY", "") or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urlrequest.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else ""
        # A 4xx is only the user's fault while verifying a code they typed.
        # Everywhere else (listing factors, opening a challenge) they have typed
        # nothing yet, so blaming their code hides our bug behind a plausible
        # error message -- which is precisely how the 405 on the old `/factors`
        # call looked like "wrong code" to the one person who hit it.
        if 400 <= exc.code < 500:
            if bad_request_is_user_error:
                logger.info("Supabase MFA verify rejected (%s): %s", exc.code, detail)
                raise StepUpError("That code was not accepted.") from exc
            logger.warning("Supabase auth call failed (%s) on %s: %s", exc.code, path, detail)
            raise StepUpUnavailable("Could not reach the authentication service.") from exc
        logger.warning("Supabase factors call failed (%s): %s", exc.code, detail)
        raise StepUpUnavailable("Could not reach the authentication service.") from exc
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("Supabase factors call errored: %s", exc)
        raise StepUpUnavailable("Could not reach the authentication service.") from exc


def _verified_totp_factor_id(user_jwt: str) -> str:
    """The user's verified TOTP factor, or "" if they have none.

    Read off the user object. GoTrue has no listing endpoint: `/factors` accepts
    POST (enroll) only and answers GET with 405, which is exactly how this got
    shipped broken -- supabase-js's `mfa.listFactors()` does the same thing,
    calling getUser() and reading `user.factors`.

    A factor that was enrolled but never verified must not count: it would let
    somebody register a factor they control and immediately "confirm" with it.
    """
    payload = _supabase_call("GET", "/user", user_jwt)
    for factor in payload.get("factors") or []:
        if factor.get("status") == "verified" and factor.get("factor_type") == "totp":
            return str(factor.get("id") or "")
    return ""


def _send_code_email(profile: UserProfile, code: str, purpose: str) -> None:
    """Mail the code.

    Sent through `_send_branded` rather than the admin-editable
    `_send_templated` path used by lifecycle mail, on purpose. Those templates
    carry an `enabled` switch and swallow send failures; either behaviour here
    would lock a user out of confirming anything, with no clue why.
    """
    from payglue_backend.authn.lifecycle_emails import _send_branded

    action = dict(StepUpChallenge.Purpose.choices).get(purpose, purpose)
    _send_branded(
        f"Your PayGlue confirmation code: {code}",
        (
            f"Someone asked to confirm this action on your account: {action}.\n\n"
            f"Your confirmation code is {code}. It expires in 10 minutes.\n\n"
            "If this was not you, do not enter the code. Your account is unchanged, "
            "but you should sign out of any device you do not recognise and turn on "
            "two-factor authentication in Preferences.\n\n"
            "__\nCheers,\nPayGlue - Team"
        ),
        [profile.email],
    )


def issue_challenge(profile: UserProfile, purpose: str, user_jwt: str) -> ChallengeIssued:
    """Start a confirmation. TOTP when the account has it, emailed code otherwise."""
    if purpose not in StepUpChallenge.Purpose.values:
        raise StepUpError("Unknown confirmation purpose.")

    # Supersede anything still pending for the same purpose, so a user who
    # reopens the dialog is not racing an older code against a newer one.
    StepUpChallenge.objects.filter(
        user_profile=profile, purpose=purpose, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())

    expires_at = timezone.now() + timedelta(seconds=StepUpChallenge.TTL_SECONDS)
    factor_id = _verified_totp_factor_id(user_jwt)

    if factor_id:
        challenge = _supabase_call("POST", f"/factors/{factor_id}/challenge", user_jwt)
        challenge_id = str(challenge.get("id") or "")
        if not challenge_id:
            raise StepUpUnavailable("Could not start the authenticator challenge.")
        StepUpChallenge.objects.create(
            user_profile=profile,
            purpose=purpose,
            method=StepUpChallenge.Method.TOTP,
            factor_id=factor_id,
            challenge_id=challenge_id,
            expires_at=expires_at,
        )
        return ChallengeIssued(method=StepUpChallenge.Method.TOTP, challenge_id=challenge_id)

    code = _generate_step_up_code()
    StepUpChallenge.objects.create(
        user_profile=profile,
        purpose=purpose,
        method=StepUpChallenge.Method.EMAIL,
        code_hash=_hash_step_up_secret(code),
        expires_at=expires_at,
    )
    _send_code_email(profile, code, purpose)
    return ChallengeIssued(method=StepUpChallenge.Method.EMAIL)


def verify_challenge(profile: UserProfile, purpose: str, code: str, user_jwt: str) -> str:
    """Check the code and hand back a single-use grant token."""
    challenge = (
        StepUpChallenge.objects.filter(
            user_profile=profile, purpose=purpose, consumed_at__isnull=True
        )
        .order_by("-created_at")
        .first()
    )
    if challenge is None:
        raise StepUpError("Start the confirmation again.")
    if challenge.expires_at <= timezone.now():
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["consumed_at"])
        raise StepUpError("That code expired. Start the confirmation again.")
    if challenge.attempts >= StepUpChallenge.MAX_ATTEMPTS:
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["consumed_at"])
        raise StepUpError("Too many attempts. Start the confirmation again.")

    # Count the attempt before checking it, so a crash mid-verify cannot hand
    # out a free guess.
    challenge.attempts += 1
    challenge.save(update_fields=["attempts"])

    code = (code or "").strip()
    if challenge.method == StepUpChallenge.Method.TOTP:
        # Raises StepUpError when Supabase rejects the code.
        _supabase_call(
            "POST",
            f"/factors/{challenge.factor_id}/verify",
            user_jwt,
            {"challenge_id": challenge.challenge_id, "code": code},
            bad_request_is_user_error=True,
        )
    else:
        expected = challenge.code_hash
        # compare_digest so a wrong code cannot be narrowed down by timing.
        if not secrets.compare_digest(expected, _hash_step_up_secret(code)):
            raise StepUpError("That code was not accepted.")

    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at"])

    token = secrets.token_urlsafe(32)
    StepUpGrant.objects.create(
        user_profile=profile,
        purpose=purpose,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=timezone.now() + timedelta(seconds=StepUpGrant.TTL_SECONDS),
    )
    return token


def require_step_up(request: object, profile: UserProfile, purpose: str) -> None:
    """Spend a grant, or refuse the action.

    Every destructive endpoint calls this. The grant is single use: confirming
    an owner transfer must not silently also authorise deleting the account.
    """
    token = request.headers.get(STEP_UP_HEADER, "").strip()
    if not token:
        raise StepUpError("This action needs to be confirmed.")

    grant = StepUpGrant.objects.filter(
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        user_profile=profile,
        purpose=purpose,
        consumed_at__isnull=True,
    ).first()
    if grant is None:
        raise StepUpError("This action needs to be confirmed.")
    if grant.expires_at <= timezone.now():
        raise StepUpError("That confirmation expired. Please confirm again.")

    grant.consumed_at = timezone.now()
    grant.save(update_fields=["consumed_at"])

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Identity on this server instead of in a hosted provider (PG-237).

Running PayGlue yourself should not begin with signing up for somebody else's
service. With LOCAL_AUTH_ENABLED the accounts live in this database: Django
hashes the passwords, Django's token generator carries the reset links, and
this module signs the bearer tokens the API already expects.

The shape is deliberately the same as the hosted path rather than a second one
beside it. A token is a JWT, it arrives in the Authorization header, it is
verified by a branch of get_auth_token_verifier(), and it resolves to a
UserProfile through the same invite gate. Nothing downstream can tell the two
apart, which is the point: whatever is true of the hosted product stays true
here, including the parts nobody remembers to test.

What this deliberately does NOT do:

* No TOTP. Django has no equivalent, and half of one is worse than none. The
  step-up flow already falls back to a code by email.
* No server-side session to log out of. Tokens are short-lived and the client
  drops them. What a logout must actually guarantee, that a stolen token stops
  working once the password changes, is covered: the token carries a fingerprint
  of the password hash and verification checks it against the row.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils import timezone

from payglue_backend.authn.invitations import normalize_email
from payglue_backend.tenants.models import UserProfile

# Marks a token as ours. Without it a token minted by a Supabase project that
# happens to share a secret would sail straight through.
ISSUER = "payglue-local"

# Every locally created identity gets this prefix in firebase_uid, so the
# origin of an account is readable in the database without a join.
UID_PREFIX = "local:"


class LocalAuthError(Exception):
    """Credentials were wrong, or the account cannot sign in this way."""


class LocalAuthDisabled(Exception):
    """Local accounts are not the identity provider on this installation."""


def is_enabled() -> bool:
    return bool(getattr(settings, "LOCAL_AUTH_ENABLED", False))


def _signing_key() -> bytes:
    """LOCAL_AUTH_JWT_SECRET when set, otherwise the Django secret key.

    Falling back means one less thing to configure for someone who just wants
    to start the thing, and rotating SECRET_KEY invalidating every token is the
    behaviour you would want anyway. A separate value stays available for
    installations that rotate the two on different schedules.
    """
    secret = getattr(settings, "LOCAL_AUTH_JWT_SECRET", "") or settings.SECRET_KEY
    return secret.encode("utf-8")


def _token_ttl_seconds() -> int:
    return int(getattr(settings, "LOCAL_AUTH_TOKEN_TTL_HOURS", 12)) * 3600


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def password_fingerprint(password_hash: str) -> str:
    """A short, non-reversible stand-in for the current password.

    Put in the token and compared on every request. Changing the password
    changes the hash, which changes this, which retires every token issued
    before the change. The hash itself never leaves the database.
    """
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def issue_token(profile: UserProfile) -> tuple[str, int]:
    """Returns (token, unix expiry) for an account that has just proven itself."""
    now = int(time.time())
    expires_at = now + _token_ttl_seconds()
    payload = {
        "iss": ISSUER,
        "sub": profile.firebase_uid,
        "email": profile.email,
        "iat": now,
        "exp": expires_at,
        "pwd": password_fingerprint(profile.password),
    }
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    signature = _b64(hmac.new(_signing_key(), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{signature}", expires_at


def authenticate(email: str, password: str) -> UserProfile:
    """The one place a password is checked. Raises LocalAuthError otherwise.

    Runs the hasher even when no account matches, so the response time does not
    tell an attacker which addresses exist here.
    """
    if not is_enabled():
        raise LocalAuthDisabled

    normalized = normalize_email(email)
    profile = UserProfile.objects.filter(email=normalized).first()
    stored = profile.password if profile is not None else ""
    if not stored:
        # A real hash so the comparison costs what a real one costs.
        make_password(password)
        raise LocalAuthError("Email or password is incorrect.")

    if not check_password(password, stored):
        raise LocalAuthError("Email or password is incorrect.")

    profile.last_login = timezone.now()
    profile.save(update_fields=["last_login", "updated_at"])
    return profile


def set_password(profile: UserProfile, raw_password: str) -> None:
    profile.password = make_password(raw_password)
    profile.save(update_fields=["password", "updated_at"])


def has_local_password(profile: UserProfile) -> bool:
    return bool(profile.password)


def installation_has_users() -> bool:
    return UserProfile.objects.exists()


def create_user(email: str, password: str) -> UserProfile:
    """Creates a local account. Does NOT decide whether one may be created.

    The gate lives in the callers: bootstrap_first_user() for the very first
    account, the invitation gate for every one after it. Keeping the two apart
    means neither can be bypassed by reaching for the other.
    """
    normalized = normalize_email(email)
    profile = UserProfile.objects.create(
        firebase_uid=f"{UID_PREFIX}{uuid.uuid4().hex}",
        email=normalized,
        password=make_password(password),
    )
    return profile


def bootstrap_first_user(email: str, password: str) -> UserProfile:
    """Creates the first account on an installation that has none.

    The check is the whole security of the setup wizard, which is why it is
    here and not in the interface. An installation that is reachable from the
    internet and has an open registration endpoint is the easiest way there is
    to lose it, so the second caller of this gets nothing: once a single
    UserProfile exists, this raises, permanently.
    """
    if not is_enabled():
        raise LocalAuthDisabled
    if installation_has_users():
        raise LocalAuthError("This installation already has an account.")
    return create_user(email, password)


class _ProfileTokenGenerator(PasswordResetTokenGenerator):
    """Django's generator, pointed at UserProfile.

    It only ever reads pk, password, last_login and email off the object, all
    of which this model has. Folding the password hash in is what makes a reset
    link stop working the moment it has been used.
    """

    def _make_hash_value(self, user: UserProfile, timestamp: int) -> str:
        login_timestamp = "" if user.last_login is None else user.last_login.replace(
            microsecond=0, tzinfo=None
        )
        return f"{user.pk}{user.password}{login_timestamp}{timestamp}{user.email}"


_token_generator = _ProfileTokenGenerator()


def make_reset_token(profile: UserProfile) -> str:
    return _token_generator.make_token(profile)


def check_reset_token(profile: UserProfile, token: str) -> bool:
    return _token_generator.check_token(profile, token)


def reset_identifier(profile: UserProfile) -> str:
    """The opaque part of a reset link that names the account.

    Not the primary key in the clear: a reset link ends up in mail archives and
    browser history, and a sequential id there is an invitation to try the
    neighbouring numbers.
    """
    return base64.urlsafe_b64encode(str(profile.pk).encode()).decode().rstrip("=")


def profile_from_reset_identifier(identifier: str) -> UserProfile | None:
    try:
        padding = "=" * (-len(identifier) % 4)
        pk = int(base64.urlsafe_b64decode(identifier + padding).decode())
    except Exception:
        return None
    return UserProfile.objects.filter(pk=pk).first()


def generate_password() -> str:
    """A password for an account created on someone's behalf, e.g. an invite."""
    return secrets.token_urlsafe(18)

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import re

from django.db import IntegrityError
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from payglue_backend.authn.profile_gate import (
    InviteGateError,
    resolve_profile_with_invite_gate,
)
from payglue_backend.authn.verifier import (
    AuthVerificationUnavailableError,
    ExpiredAuthTokenError,
    InvalidAuthTokenError,
    get_auth_token_verifier,
)
from payglue_backend.tenants.models import UserProfile

_BEARER_PATTERN = re.compile(
    r"^Bearer\s+(?P<token>[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)$",
    flags=re.IGNORECASE,
)


class FirebaseBearerAuthentication(BaseAuthentication):
    def authenticate_header(self, request: object) -> str:
        del request
        return "Bearer"

    def authenticate(self, request: object) -> tuple[UserProfile, None]:
        auth_header = request.headers.get("Authorization")
        if auth_header is None:
            raise AuthenticationFailed("Authorization header is required.")

        match = _BEARER_PATTERN.match(auth_header)
        if match is None:
            raise AuthenticationFailed("Authorization header must be Bearer <jwt>.")

        token = match.group("token")
        verifier = get_auth_token_verifier()
        try:
            claims = verifier.verify(token)
        except ExpiredAuthTokenError as exc:
            raise AuthenticationFailed("Authentication token is expired.") from exc
        except InvalidAuthTokenError as exc:
            raise AuthenticationFailed("Authentication token is invalid.") from exc
        except AuthVerificationUnavailableError as exc:
            raise AuthenticationFailed(
                "Authentication service is unavailable."
            ) from exc

        # Same invite-gated resolution AuthSessionView uses, so a brand-new
        # invited user's very first authenticated call (whichever endpoint
        # that happens to be) still provisions their profile correctly, while
        # a verified JWT with no invite behind it (e.g. an uninvited OAuth
        # sign-in) is rejected rather than silently provisioned.
        try:
            profile = resolve_profile_with_invite_gate(claims)
        except IntegrityError as exc:
            raise AuthenticationFailed("Authentication profile conflict.") from exc
        except InviteGateError as exc:
            raise AuthenticationFailed(str(exc)) from exc

        request._request.user_profile = profile
        return profile, None

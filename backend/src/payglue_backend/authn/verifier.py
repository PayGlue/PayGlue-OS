# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import base64
import json
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from django.conf import settings


class AuthTokenError(Exception):
    """Base auth token verification error."""


class InvalidAuthTokenError(AuthTokenError):
    """Token failed verification."""


class ExpiredAuthTokenError(AuthTokenError):
    """Token is expired."""


class AuthVerificationUnavailableError(AuthTokenError):
    """Token verification backend is unavailable."""


@dataclass(frozen=True)
class VerifiedTokenClaims:
    firebase_uid: str
    email: str


class AuthTokenVerifier(Protocol):
    def verify(self, token: str) -> VerifiedTokenClaims: ...


class RejectingAuthTokenVerifier:
    def verify(self, token: str) -> VerifiedTokenClaims:
        del token
        raise InvalidAuthTokenError


class FirebaseAuthTokenVerifier:
    def verify(self, token: str) -> VerifiedTokenClaims:
        try:
            from firebase_admin import auth, get_app, initialize_app
        except ImportError as exc:
            raise AuthVerificationUnavailableError from exc

        try:
            get_app()
        except ValueError:
            initialize_app()

        decoded = _decode_with_firebase(auth, token)
        firebase_uid = decoded.get("uid")
        email = decoded.get("email")
        if not isinstance(firebase_uid, str) or not isinstance(email, str) or not email:
            raise InvalidAuthTokenError

        return VerifiedTokenClaims(firebase_uid=firebase_uid, email=email)


def _decode_with_firebase(auth: Any, token: str) -> dict[str, object]:
    try:
        return auth.verify_id_token(token, check_revoked=True)
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise AuthVerificationUnavailableError from exc
        exc_name = exc.__class__.__name__
        if "Expired" in exc_name:
            raise ExpiredAuthTokenError from exc
        if any(
            marker in exc_name
            for marker in ("CertificateFetch", "Transport", "Unavailable", "Timeout")
        ):
            raise AuthVerificationUnavailableError from exc
        raise InvalidAuthTokenError from exc


def _decode_jwt_payload(payload_b64: str) -> dict:
    padding = "=" * (-len(payload_b64) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    except Exception as exc:
        raise InvalidAuthTokenError from exc


def _extract_claims(payload: dict) -> VerifiedTokenClaims:
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and time.time() > exp:
        raise ExpiredAuthTokenError

    uid = payload.get("sub")
    email = payload.get("email")
    if not isinstance(uid, str) or not uid:
        raise InvalidAuthTokenError
    if not isinstance(email, str) or not email:
        email = payload.get("user_metadata", {}).get("email", "")
    if not email:
        raise InvalidAuthTokenError

    return VerifiedTokenClaims(firebase_uid=uid, email=email)


class SupabaseJwksVerifier:
    """Verifies Supabase JWTs using the JWKS endpoint (supports ES256 / P-256)."""

    _CACHE_TTL = 3600  # re-fetch keys after 1 hour

    def __init__(self, jwks_url: str) -> None:
        self._jwks_url = jwks_url
        self._keys: dict[str, Any] = {}
        self._fetched_at: float = 0.0

    def _get_keys(self) -> dict[str, Any]:
        import urllib.request

        if time.time() - self._fetched_at < self._CACHE_TTL and self._keys:
            return self._keys

        try:
            with urllib.request.urlopen(self._jwks_url, timeout=5) as resp:
                jwks = json.loads(resp.read())
        except Exception as exc:
            if not self._keys:
                raise AuthVerificationUnavailableError from exc
            return self._keys  # use stale cache rather than failing

        self._keys = {k["kid"]: k for k in jwks.get("keys", []) if "kid" in k}
        self._fetched_at = time.time()
        return self._keys

    def _verify_es256(self, signing_input: bytes, sig_b64: str, jwk: dict) -> None:
        from cryptography.hazmat.primitives.asymmetric.ec import (
            ECDSA,
            EllipticCurvePublicNumbers,
            SECP256R1,
        )
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.asymmetric.utils import (
            encode_dss_signature,
        )

        try:
            padding = "=" * (-len(sig_b64) % 4)
            raw_sig = base64.urlsafe_b64decode(sig_b64 + padding)
            # ES256 raw signature is r || s, each 32 bytes
            if len(raw_sig) != 64:
                raise InvalidAuthTokenError
            r = int.from_bytes(raw_sig[:32], "big")
            s = int.from_bytes(raw_sig[32:], "big")
            der_sig = encode_dss_signature(r, s)

            x = int.from_bytes(base64.urlsafe_b64decode(jwk["x"] + "=="), "big")
            y = int.from_bytes(base64.urlsafe_b64decode(jwk["y"] + "=="), "big")
            pub_key = EllipticCurvePublicNumbers(x, y, SECP256R1()).public_key()
            pub_key.verify(der_sig, signing_input, ECDSA(SHA256()))
        except InvalidAuthTokenError:
            raise
        except Exception as exc:
            raise InvalidAuthTokenError from exc

    def verify(self, token: str) -> VerifiedTokenClaims:
        parts = token.split(".")
        if len(parts) != 3:
            raise InvalidAuthTokenError

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode()

        try:
            header_padding = "=" * (-len(header_b64) % 4)
            header = json.loads(base64.urlsafe_b64decode(header_b64 + header_padding))
        except Exception as exc:
            raise InvalidAuthTokenError from exc

        alg = header.get("alg", "")
        kid = header.get("kid", "")

        if alg == "ES256":
            keys = self._get_keys()
            jwk = keys.get(kid) or (next(iter(keys.values())) if keys else None)
            if not jwk:
                raise AuthVerificationUnavailableError
            self._verify_es256(signing_input, sig_b64, jwk)
        else:
            raise InvalidAuthTokenError

        payload = _decode_jwt_payload(payload_b64)
        return _extract_claims(payload)


class SupabaseJwtVerifier:
    """Legacy HS256 verifier -- kept for tokens issued before key rotation."""

    def __init__(self, jwt_secret: str) -> None:
        self._secret = jwt_secret.encode("utf-8")

    def verify(self, token: str) -> VerifiedTokenClaims:
        import hashlib
        import hmac as hmac_mod

        parts = token.split(".")
        if len(parts) != 3:
            raise InvalidAuthTokenError

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

        expected_sig = hmac_mod.new(self._secret, signing_input, hashlib.sha256).digest()
        try:
            padding = "=" * (-len(sig_b64) % 4)
            received_sig = base64.urlsafe_b64decode(sig_b64 + padding)
        except Exception as exc:
            raise InvalidAuthTokenError from exc
        if not hmac_mod.compare_digest(expected_sig, received_sig):
            raise InvalidAuthTokenError

        payload = _decode_jwt_payload(payload_b64)
        return _extract_claims(payload)


@lru_cache(maxsize=1)
def get_auth_token_verifier() -> AuthTokenVerifier:
    if getattr(settings, "FIREBASE_AUTH_ENABLED", False):
        return FirebaseAuthTokenVerifier()
    jwks_url = getattr(settings, "SUPABASE_JWKS_URL", "")
    jwks_keys_json = getattr(settings, "SUPABASE_JWKS_KEYS", "")
    if isinstance(jwks_url, str) and jwks_url:
        verifier = SupabaseJwksVerifier(jwks_url)
        # Pre-populate key cache from env var to avoid DNS on cold start
        if isinstance(jwks_keys_json, str) and jwks_keys_json:
            try:
                jwks = json.loads(jwks_keys_json)
                verifier._keys = {k["kid"]: k for k in jwks.get("keys", []) if "kid" in k}
                # Set far in the future so cache never expires and never triggers
                # a DNS-blocking refresh. Key rotation happens via redeploy.
                verifier._fetched_at = time.time() + 86400 * 365
            except Exception:
                pass
        return verifier
    supabase_secret = getattr(settings, "SUPABASE_JWT_SECRET", "")
    if isinstance(supabase_secret, str) and supabase_secret:
        return SupabaseJwtVerifier(supabase_secret)
    return RejectingAuthTokenVerifier()

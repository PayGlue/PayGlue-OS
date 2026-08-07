# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Accounts that live on this server (PG-237).

The point of these is the shape of the thing, not the happy path: an
installation that issues its own identities is one somebody put on the
internet themselves, and the two ways to lose it are an open registration
endpoint and a token that outlives the password it was issued against.
"""
import time

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import Client

from payglue_backend.authn import local_identity
from payglue_backend.authn.verifier import (
    InvalidAuthTokenError,
    LocalAuthTokenVerifier,
    RejectingAuthTokenVerifier,
    SupabaseJwtVerifier,
    get_auth_token_verifier,
)
from payglue_backend.tenants.models import UserProfile

pytestmark = pytest.mark.django_db

GOOD_PASSWORD = "correct-horse-staple-42"


@pytest.fixture(autouse=True)
def _clean_throttle_state() -> None:
    # The throttle counts per address in the shared cache, so without this one
    # test's sign-in attempts spend the next test's budget.
    cache.clear()


@pytest.fixture
def local_mode(settings):
    settings.LOCAL_AUTH_ENABLED = True
    settings.LOCAL_AUTH_JWT_SECRET = "test-local-signing-secret"
    get_auth_token_verifier.cache_clear()
    yield settings
    get_auth_token_verifier.cache_clear()


def _bootstrap(client: Client, email: str = "owner@example.com") -> dict:
    resp = client.post(
        "/api/v1/auth/local/bootstrap",
        data={"email": email, "password": GOOD_PASSWORD},
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()


class TestTheGate:
    """Who may create an account, and when."""

    def test_the_first_account_may_be_created_without_credentials(self, local_mode) -> None:
        body = _bootstrap(Client())
        assert body["user"]["email"] == "owner@example.com"
        assert UserProfile.objects.count() == 1

    def test_the_second_one_may_not(self, local_mode) -> None:
        client = Client()
        _bootstrap(client)
        resp = client.post(
            "/api/v1/auth/local/bootstrap",
            data={"email": "someone-else@example.com", "password": GOOD_PASSWORD},
            content_type="application/json",
        )
        assert resp.status_code == 409
        assert UserProfile.objects.count() == 1

    def test_the_gate_reads_the_database_not_the_request(self, local_mode) -> None:
        # No wizard involved: a profile created by any other path closes it too.
        UserProfile.objects.create(firebase_uid="sub-from-elsewhere", email="a@example.com")
        resp = Client().post(
            "/api/v1/auth/local/bootstrap",
            data={"email": "attacker@example.com", "password": GOOD_PASSWORD},
            content_type="application/json",
        )
        assert resp.status_code == 409

    def test_a_weak_password_is_refused(self, local_mode) -> None:
        resp = Client().post(
            "/api/v1/auth/local/bootstrap",
            data={"email": "owner@example.com", "password": "12345678"},
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "password" in resp.json()
        assert UserProfile.objects.count() == 0


class TestNotThereWhenSwitchedOff:
    """On the hosted product these routes must not exist."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/auth/local/token",
            "/api/v1/auth/local/bootstrap",
            "/api/v1/auth/local/password/reset",
            "/api/v1/auth/local/password/reset/confirm",
        ],
    )
    def test_endpoints_answer_404(self, settings, path) -> None:
        settings.LOCAL_AUTH_ENABLED = False
        resp = Client().post(path, data={}, content_type="application/json")
        assert resp.status_code == 404

    def test_status_says_so_without_giving_anything_else_away(self, settings) -> None:
        settings.LOCAL_AUTH_ENABLED = False
        body = Client().get("/api/v1/auth/local/status").json()
        assert body == {"enabled": False, "needs_setup": False}

    def test_status_reports_setup_only_until_the_first_account(self, local_mode) -> None:
        client = Client()
        assert client.get("/api/v1/auth/local/status").json() == {
            "enabled": True,
            "needs_setup": True,
        }
        _bootstrap(client)
        assert client.get("/api/v1/auth/local/status").json() == {
            "enabled": True,
            "needs_setup": False,
        }


class TestSigningIn:
    def test_right_password_returns_a_usable_token(self, local_mode) -> None:
        client = Client()
        _bootstrap(client)
        resp = client.post(
            "/api/v1/auth/local/token",
            data={"email": "owner@example.com", "password": GOOD_PASSWORD},
            content_type="application/json",
        )
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        # The token has to work on a normal authenticated endpoint, not just
        # look right: that is the whole claim being made here.
        session = client.post(
            "/api/v1/auth/session",
            data={},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert session.status_code == 200, session.content

    def test_wrong_password_and_unknown_address_are_indistinguishable(self, local_mode) -> None:
        client = Client()
        _bootstrap(client)
        wrong = client.post(
            "/api/v1/auth/local/token",
            data={"email": "owner@example.com", "password": "not-the-password"},
            content_type="application/json",
        )
        unknown = client.post(
            "/api/v1/auth/local/token",
            data={"email": "nobody@example.com", "password": GOOD_PASSWORD},
            content_type="application/json",
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

    def test_an_account_without_a_local_password_cannot_sign_in_this_way(
        self, local_mode
    ) -> None:
        UserProfile.objects.create(firebase_uid="hosted-identity", email="hosted@example.com")
        resp = Client().post(
            "/api/v1/auth/local/token",
            data={"email": "hosted@example.com", "password": GOOD_PASSWORD},
            content_type="application/json",
        )
        assert resp.status_code == 401


class TestTokens:
    def test_the_verifier_rejects_a_token_signed_with_another_key(self, local_mode) -> None:
        profile = local_identity.create_user("owner@example.com", GOOD_PASSWORD)
        token, _ = local_identity.issue_token(profile)
        local_mode.LOCAL_AUTH_JWT_SECRET = "a-different-secret"
        with pytest.raises(InvalidAuthTokenError):
            LocalAuthTokenVerifier().verify(token)

    def test_a_supabase_token_is_not_accepted_here(self, local_mode) -> None:
        # Same algorithm, same secret, missing our issuer claim. Without that
        # check, any project sharing a secret could mint accounts on this box.
        import base64
        import hashlib
        import hmac
        import json

        def b64(raw: bytes) -> str:
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")

        profile = local_identity.create_user("owner@example.com", GOOD_PASSWORD)
        payload = {
            "sub": profile.firebase_uid,
            "email": profile.email,
            "exp": int(time.time()) + 3600,
            "pwd": local_identity.password_fingerprint(profile.password),
        }
        header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        body = b64(json.dumps(payload).encode())
        sig = b64(
            hmac.new(
                local_identity._signing_key(), f"{header}.{body}".encode(), hashlib.sha256
            ).digest()
        )
        with pytest.raises(InvalidAuthTokenError):
            LocalAuthTokenVerifier().verify(f"{header}.{body}.{sig}")

    def test_changing_the_password_retires_every_token_issued_before_it(
        self, local_mode
    ) -> None:
        profile = local_identity.create_user("owner@example.com", GOOD_PASSWORD)
        token, _ = local_identity.issue_token(profile)
        assert LocalAuthTokenVerifier().verify(token).email == "owner@example.com"

        local_identity.set_password(profile, "an-entirely-new-password")
        with pytest.raises(InvalidAuthTokenError):
            LocalAuthTokenVerifier().verify(token)

    def test_a_deleted_account_takes_its_tokens_with_it(self, local_mode) -> None:
        profile = local_identity.create_user("owner@example.com", GOOD_PASSWORD)
        token, _ = local_identity.issue_token(profile)
        profile.delete()
        with pytest.raises(InvalidAuthTokenError):
            LocalAuthTokenVerifier().verify(token)


class TestChangingThePassword:
    def _signed_in(self, client: Client) -> str:
        return _bootstrap(client)["access_token"]

    def test_the_current_password_is_required(self, local_mode) -> None:
        client = Client()
        token = self._signed_in(client)
        resp = client.post(
            "/api/v1/auth/local/password",
            data={"current_password": "wrong", "new_password": "a-brand-new-secret-1"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert resp.status_code == 400

    def test_a_successful_change_hands_back_a_fresh_token(self, local_mode) -> None:
        client = Client()
        token = self._signed_in(client)
        resp = client.post(
            "/api/v1/auth/local/password",
            data={
                "current_password": GOOD_PASSWORD,
                "new_password": "a-brand-new-secret-1",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert resp.status_code == 200, resp.content
        new_token = resp.json()["access_token"]
        assert new_token != token
        assert LocalAuthTokenVerifier().verify(new_token).email == "owner@example.com"
        with pytest.raises(InvalidAuthTokenError):
            LocalAuthTokenVerifier().verify(token)


class TestResettingAForgottenPassword:
    def test_the_answer_never_reveals_whether_the_address_is_known(self, local_mode) -> None:
        client = Client()
        _bootstrap(client)
        known = client.post(
            "/api/v1/auth/local/password/reset",
            data={"email": "owner@example.com"},
            content_type="application/json",
        )
        unknown = client.post(
            "/api/v1/auth/local/password/reset",
            data={"email": "nobody@example.com"},
            content_type="application/json",
        )
        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()
        assert len(mail.outbox) == 1

    def test_a_link_gets_a_new_password_in_and_then_stops_working(self, local_mode) -> None:
        local_mode.PUBLIC_APP_BASE_URL = "https://payglue.example.com"
        client = Client()
        _bootstrap(client)
        profile = UserProfile.objects.get(email="owner@example.com")
        payload = {
            "id": local_identity.reset_identifier(profile),
            "token": local_identity.make_reset_token(profile),
            "new_password": "the-replacement-secret-9",
        }

        first = client.post(
            "/api/v1/auth/local/password/reset/confirm",
            data=payload,
            content_type="application/json",
        )
        assert first.status_code == 200, first.content

        second = client.post(
            "/api/v1/auth/local/password/reset/confirm",
            data=payload,
            content_type="application/json",
        )
        assert second.status_code == 400

    def test_the_link_carries_no_readable_account_id(self, local_mode) -> None:
        local_mode.PUBLIC_APP_BASE_URL = "https://payglue.example.com"
        client = Client()
        _bootstrap(client)
        client.post(
            "/api/v1/auth/local/password/reset",
            data={"email": "owner@example.com"},
            content_type="application/json",
        )
        profile = UserProfile.objects.get(email="owner@example.com")
        body = mail.outbox[0].body
        assert "payglue.example.com/auth/reset?id=" in body
        assert f"id={profile.pk}&" not in body


class TestWhichVerifierIsInCharge:
    def test_local_wins_over_leftover_supabase_settings(self, settings) -> None:
        settings.LOCAL_AUTH_ENABLED = True
        settings.SUPABASE_JWT_SECRET = "left-over-from-an-earlier-attempt"
        settings.SUPABASE_JWKS_URL = ""
        settings.FIREBASE_AUTH_ENABLED = False
        get_auth_token_verifier.cache_clear()
        assert isinstance(get_auth_token_verifier(), LocalAuthTokenVerifier)
        get_auth_token_verifier.cache_clear()

    def test_the_hosted_product_is_unaffected(self, settings) -> None:
        settings.LOCAL_AUTH_ENABLED = False
        settings.SUPABASE_JWT_SECRET = "hosted-secret"
        settings.SUPABASE_JWKS_URL = ""
        settings.FIREBASE_AUTH_ENABLED = False
        get_auth_token_verifier.cache_clear()
        assert isinstance(get_auth_token_verifier(), SupabaseJwtVerifier)
        get_auth_token_verifier.cache_clear()

    def test_nothing_configured_still_rejects_everything(self, settings) -> None:
        settings.LOCAL_AUTH_ENABLED = False
        settings.SUPABASE_JWT_SECRET = ""
        settings.SUPABASE_JWKS_URL = ""
        settings.FIREBASE_AUTH_ENABLED = False
        get_auth_token_verifier.cache_clear()
        assert isinstance(get_auth_token_verifier(), RejectingAuthTokenVerifier)
        get_auth_token_verifier.cache_clear()

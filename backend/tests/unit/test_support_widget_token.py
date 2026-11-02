# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The support widget only trusts an identity it can verify, so the token has to
be exactly what an HS256 verifier expects, and the endpoint has to stay shut on
an installation without a widget secret."""
import base64
import hashlib
import hmac
import json

import pytest
from django.test import override_settings
from rest_framework.test import APIRequestFactory

from payglue_backend.http import support_widget
from payglue_backend.http.support_widget import (
    TOKEN_TTL_SECONDS,
    SupportWidgetTokenView,
    sign_widget_token,
)


def _decode(part: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def test_token_verifies_with_the_secret_and_carries_identity() -> None:
    token = sign_widget_token(
        user_id="uid-1", email="a@example.com", name="Ada Lovelace", secret="s3cret", now=1000
    )
    header, body, sig = token.split(".")
    expected = hmac.new(b"s3cret", f"{header}.{body}".encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)) == expected
    assert _decode(header) == {"alg": "HS256", "typ": "JWT"}
    assert _decode(body) == {
        "sub": "uid-1",
        "email": "a@example.com",
        "name": "Ada Lovelace",
        "iat": 1000,
        "exp": 1000 + TOKEN_TTL_SECONDS,
    }


def test_name_is_left_out_when_unknown() -> None:
    token = sign_widget_token(user_id="uid-1", email="a@example.com", name="", secret="s", now=1)
    assert "name" not in _decode(token.split(".")[1])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Ada   Lovelace ", "Ada Lovelace"),
        ("", ""),
        (None, ""),
        ("x" * 300, "x" * 100),
    ],
)
def test_display_name_is_tidied_and_capped(raw, expected) -> None:
    assert support_widget._display_name(raw) == expected


class _Profile:
    firebase_uid = "uid-9"
    email = "nine@example.com"


def _call(monkeypatch):
    monkeypatch.setattr(
        SupportWidgetTokenView, "authentication_classes", [], raising=True
    )
    request = APIRequestFactory().get("/api/v1/support/widget-token", {"name": "Nine"})
    request.user_profile = _Profile()
    return SupportWidgetTokenView.as_view()(request)


@override_settings(SUPPORT_WIDGET_SECRET="")
def test_endpoint_is_off_without_a_secret(monkeypatch) -> None:
    assert _call(monkeypatch).status_code == 404


@override_settings(SUPPORT_WIDGET_SECRET="s3cret")
def test_endpoint_signs_for_the_signed_in_profile(monkeypatch) -> None:
    response = _call(monkeypatch)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"
    body = _decode(response.data["token"].split(".")[1])
    assert (body["sub"], body["email"], body["name"]) == ("uid-9", "nine@example.com", "Nine")

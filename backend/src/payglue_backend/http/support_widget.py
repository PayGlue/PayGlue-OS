# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Sign-in token for the support widget in the dashboard.

The widget comes from a separate FeedbackOS instance. It only accepts an
identity it can verify: a short HS256 JWT carrying id, email and name, signed
with the widget secret that instance hands out. Without it every customer
shows up there as an anonymous visitor with a made-up name, and a reply can
not be matched to an account.

The secret lives in SUPPORT_WIDGET_SECRET. Unset means no widget on this
installation, so the endpoint answers 404 and the dashboard skips identify.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from django.conf import settings
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from payglue_backend.authn.authentication import SupabaseBearerAuthentication
from payglue_backend.authn.views import HasUserProfile

# Long enough for a slow page load, short enough that a token copied out of the
# browser is useless by the time anybody tries it. The widget turns it into its
# own session straight away, so nothing needs it afterwards.
TOKEN_TTL_SECONDS = 600


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# A display name is cosmetic: it is what the support inbox shows instead of an
# email address. The verified token claims carry no name, so the dashboard
# sends the one it shows in its own header. Trusting it is harmless, the
# identity itself (id and email) comes from the verified session.
MAX_NAME = 100


def _display_name(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    return " ".join(raw.split())[:MAX_NAME]


def sign_widget_token(
    *, user_id: str, email: str, name: str, secret: str, now: int | None = None
) -> str:
    issued = int(time.time()) if now is None else now
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "iat": issued,
        "exp": issued + TOKEN_TTL_SECONDS,
    }
    if name:
        payload["name"] = name
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


class SupportWidgetTokenView(APIView):
    authentication_classes = [SupabaseBearerAuthentication]
    permission_classes = [HasUserProfile]

    def get(self, request: Request) -> Response:
        secret = getattr(settings, "SUPPORT_WIDGET_SECRET", "")
        if not secret:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        profile = request.user_profile
        token = sign_widget_token(
            user_id=profile.firebase_uid,
            email=profile.email,
            name=_display_name(request.query_params.get("name")),
            secret=secret,
        )
        response = Response({"token": token})
        response["Cache-Control"] = "no-store"
        return response

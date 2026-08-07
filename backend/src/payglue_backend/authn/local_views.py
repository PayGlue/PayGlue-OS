# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Endpoints for accounts that live on this server (PG-237).

Every one of them answers 404 when local accounts are not the identity
provider here. Not 403: on the hosted product these routes do not exist as far
as anyone outside is concerned, and an endpoint that admits to being switched
off is an endpoint worth coming back to.

The gate that matters is in BootstrapView. Account creation is open exactly
until the first account exists, and the check for that is a COUNT on this
database, not a flag the client sends.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import CharField, EmailField, Serializer
from rest_framework.views import APIView

from payglue_backend.authn import local_identity
from payglue_backend.authn.authentication import SupabaseBearerAuthentication
from payglue_backend.authn.invitations import normalize_email
from payglue_backend.authn.lifecycle_emails import _send_branded
from payglue_backend.authn.views import HasUserProfile
from payglue_backend.http.throttling import DynamicScopedRateThrottle
from payglue_backend.tenants.models import UserProfile

logger = logging.getLogger(__name__)


def _not_found() -> Response:
    return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)


def _validated_password(password: str, email: str) -> None:
    """Raises DjangoValidationError with messages fit to show the person."""
    validate_password(password, user=UserProfile(email=email))


def _token_response(profile: UserProfile) -> Response:
    token, expires_at = local_identity.issue_token(profile)
    return Response(
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires_at,
            "user": {"id": profile.firebase_uid, "email": profile.email},
        }
    )


class LocalAuthStatusView(APIView):
    """What the sign-in screen needs to know before anyone types anything.

    Public by necessity: it is what tells the frontend whether to render a
    password form or send the browser to a hosted provider. `needs_setup` says
    the installation has no account yet, which is the one moment the setup
    wizard may appear. That is not a secret worth keeping; anyone can observe
    it by watching the wizard show up.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        del request
        if not local_identity.is_enabled():
            return Response({"enabled": False, "needs_setup": False})
        return Response(
            {
                "enabled": True,
                "needs_setup": not local_identity.installation_has_users(),
            }
        )


class _CredentialsSerializer(Serializer):
    email = EmailField()
    password = CharField()


class LocalTokenView(APIView):
    """Email and password in, bearer token out."""

    authentication_classes: list = []
    permission_classes: list = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_local_token"

    def post(self, request: Request) -> Response:
        if not local_identity.is_enabled():
            return _not_found()
        serializer = _CredentialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            profile = local_identity.authenticate(
                serializer.validated_data["email"], serializer.validated_data["password"]
            )
        except local_identity.LocalAuthError as exc:
            # One message for "no such account" and for "wrong password". The
            # difference is exactly what someone probing a list of addresses is
            # after.
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)
        return _token_response(profile)


class _BootstrapSerializer(Serializer):
    email = EmailField()
    password = CharField()


class LocalBootstrapView(APIView):
    """Creates the first account on an installation that has none.

    This is the only unauthenticated way an account ever comes into being, and
    it closes for good the moment it succeeds once. Everyone after the first
    person arrives through an invitation, checked in the same gate the hosted
    product uses.
    """

    authentication_classes: list = []
    permission_classes: list = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_local_bootstrap"

    def post(self, request: Request) -> Response:
        if not local_identity.is_enabled():
            return _not_found()
        serializer = _BootstrapSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        try:
            _validated_password(password, email)
        except DjangoValidationError as exc:
            return Response({"password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            profile = local_identity.bootstrap_first_user(email, password)
        except local_identity.LocalAuthError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except IntegrityError:
            # Two setup forms submitted at once. The unique constraint on email
            # decides, and the loser is told the same thing as a latecomer.
            return Response(
                {"detail": "This installation already has an account."},
                status=status.HTTP_409_CONFLICT,
            )

        logger.info("Local installation bootstrapped its first account")
        return _token_response(profile)


class _ChangePasswordSerializer(Serializer):
    current_password = CharField()
    new_password = CharField()


class LocalPasswordChangeView(APIView):
    """Changes the signed-in account's password.

    The current password is required even though the request is already
    authenticated: a bearer token left behind on a shared machine should not be
    enough to lock its owner out.
    """

    authentication_classes = [SupabaseBearerAuthentication]
    permission_classes = [HasUserProfile]
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_local_token"

    def post(self, request: Request) -> Response:
        if not local_identity.is_enabled():
            return _not_found()
        serializer = _ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile: UserProfile = request.user

        try:
            local_identity.authenticate(
                profile.email, serializer.validated_data["current_password"]
            )
        except local_identity.LocalAuthError:
            return Response(
                {"detail": "Current password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_password = serializer.validated_data["new_password"]
        try:
            _validated_password(new_password, profile.email)
        except DjangoValidationError as exc:
            return Response({"new_password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        local_identity.set_password(profile, new_password)
        # Reissued rather than returning nothing: the caller's own token was
        # just invalidated along with everyone else's, which is the point, and
        # signing the person out of the tab they are standing in would be a
        # strange way to reward them for changing it.
        profile.refresh_from_db()
        return _token_response(profile)


class _ResetRequestSerializer(Serializer):
    email = EmailField()


class LocalPasswordResetRequestView(APIView):
    """Sends a reset link, or pretends to.

    The response never says whether the address is known here. It also never
    depends on mail actually going out, which is why the self-hosting guide has
    to be blunt that mail is not optional: without it, a forgotten password is
    a command-line job.
    """

    authentication_classes: list = []
    permission_classes: list = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_local_password_reset"

    def post(self, request: Request) -> Response:
        if not local_identity.is_enabled():
            return _not_found()
        serializer = _ResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = normalize_email(serializer.validated_data["email"])
        profile = UserProfile.objects.filter(email=email).first()
        if profile is not None and profile.password:
            self._send(profile)

        return Response(
            {"detail": "If that address has an account here, a reset link is on its way."}
        )

    def _send(self, profile: UserProfile) -> None:
        base_url = getattr(settings, "PUBLIC_APP_BASE_URL", "")
        identifier = local_identity.reset_identifier(profile)
        token = local_identity.make_reset_token(profile)
        link = f"{base_url}/auth/reset?id={identifier}&token={token}" if base_url else ""

        body = "Somebody asked to reset the password for this account.\n\n"
        if link:
            body += f"{link}\n\n"
        else:
            # Worth saying out loud rather than sending a mail with a hole in
            # it: the installation never got told its own address.
            body += (
                "No link could be included because this installation does not "
                "know its own address. Set PUBLIC_APP_BASE_URL and ask again.\n\n"
            )
        body += "If that was not you, nothing has changed and you can ignore this."

        try:
            _send_branded("Reset your password", body, [profile.email])
        except Exception:
            # Never surfaced to the caller: whether mail left the building is
            # not something the sign-in screen may reveal about an address.
            logger.exception("Local password reset email could not be sent")


class _ResetConfirmSerializer(Serializer):
    id = CharField()
    token = CharField()
    new_password = CharField()


class LocalPasswordResetConfirmView(APIView):
    """Redeems a reset link. Single use, because the token folds in the hash."""

    authentication_classes: list = []
    permission_classes: list = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_local_password_reset"

    def post(self, request: Request) -> Response:
        if not local_identity.is_enabled():
            return _not_found()
        serializer = _ResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile = local_identity.profile_from_reset_identifier(serializer.validated_data["id"])
        invalid = Response(
            {"detail": "This reset link is no longer valid. Please request a new one."},
            status=status.HTTP_400_BAD_REQUEST,
        )
        if profile is None or not local_identity.check_reset_token(
            profile, serializer.validated_data["token"]
        ):
            return invalid

        new_password = serializer.validated_data["new_password"]
        try:
            _validated_password(new_password, profile.email)
        except DjangoValidationError as exc:
            return Response({"new_password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        local_identity.set_password(profile, new_password)
        profile.refresh_from_db()
        return _token_response(profile)

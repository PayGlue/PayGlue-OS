# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import re

from django.conf import settings
from django.db import IntegrityError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import CharField, EmailField, Serializer
from rest_framework.views import APIView

from payglue_backend.authn.invitations import (
    invitation_code_matches,
    normalize_email,
)
from payglue_backend.authn.polar_access import (
    PolarAccessError,
    validate_checkout,
    validate_license_key,
)
from payglue_backend.authn.verifier import (
    AuthVerificationUnavailableError,
    ExpiredAuthTokenError,
    InvalidAuthTokenError,
    get_auth_token_verifier,
)
from payglue_backend.http.throttling import DynamicScopedRateThrottle
from payglue_backend.tenants.models import (
    AccessRedemption,
    InvitationGrant,
    Tenant,
    TenantMembership,
    UserProfile,
)


_BEARER_PATTERN = re.compile(
    r"^Bearer\s+(?P<token>[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)$",
    flags=re.IGNORECASE,
)


class AuthSessionView(APIView):
    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_session"

    def post(self, request: Request) -> Response:
        auth_header = request.headers.get("Authorization")
        if auth_header is None:
            return Response(
                {"detail": "Authorization header is required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        match = _BEARER_PATTERN.match(auth_header)
        if match is None:
            return Response(
                {"detail": "Authorization header must be Bearer <jwt>."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token = match.group("token")
        token_verifier = get_auth_token_verifier()
        try:
            claims = token_verifier.verify(token)
        except ExpiredAuthTokenError:
            return Response(
                {"detail": "Authentication token is expired."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except InvalidAuthTokenError:
            return Response(
                {"detail": "Authentication token is invalid."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except AuthVerificationUnavailableError:
            return Response(
                {"detail": "Authentication service is unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            profile = self._resolve_profile_with_invite_gate(claims)
        except IntegrityError:
            return Response(
                {"detail": "Authentication profile conflict."},
                status=status.HTTP_409_CONFLICT,
            )
        except _InviteGateError as error:
            return Response(
                {"detail": str(error)},
                status=error.status_code,
            )
        request.user_profile = profile
        memberships = list(
            TenantMembership.objects.filter(
                user_profile=profile,
                tenant__status=Tenant.Status.ACTIVE,
            )
            .select_related("tenant")
            .order_by("tenant__slug")
        )

        return Response(
            {
                "user": {
                    "id": profile.id,
                    "firebase_uid": profile.firebase_uid,
                    "email": profile.email,
                },
                "memberships": [
                    {
                        "tenant_slug": membership.tenant.slug,
                        "role": membership.role,
                    }
                    for membership in memberships
                ],
            },
            status=status.HTTP_200_OK,
        )

    def _resolve_profile_with_invite_gate(self, claims):
        normalized_email = normalize_email(claims.email)

        profile = UserProfile.objects.filter(firebase_uid=claims.firebase_uid).first()
        if profile is not None:
            profile.email = normalized_email
            profile.save(update_fields=["email", "updated_at"])
            return profile

        profile = UserProfile.objects.filter(email=normalized_email).first()
        if profile is not None:
            profile.firebase_uid = claims.firebase_uid
            profile.save(update_fields=["firebase_uid", "updated_at"])
            return profile

        if settings.PREFINERY_INVITE_GATE_ENABLED and normalized_email not in settings.DEV_BYPASS_EMAILS:
            if not settings.PREFINERY_INVITATION_DECODER_KEY:
                raise _InviteGateError(
                    "Invitation gate is enabled but decoder key is not configured.",
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            with transaction.atomic():
                grant = (
                    InvitationGrant.objects.select_for_update()
                    .filter(email=normalized_email, consumed_at__isnull=True)
                    .first()
                )
                if grant is None:
                    raise _InviteGateError(
                        "Invite code validation is required before creating a session.",
                        status.HTTP_403_FORBIDDEN,
                    )

                profile = UserProfile.objects.create(
                    firebase_uid=claims.firebase_uid,
                    email=normalized_email,
                )
                grant.consumed_at = timezone.now()
                grant.save(update_fields=["consumed_at", "verified_at"])
                return profile

        return UserProfile.objects.create(
            firebase_uid=claims.firebase_uid,
            email=normalized_email,
        )


class InvitationValidationSerializer(Serializer):
    email = EmailField()
    invitation_code = CharField(min_length=4, max_length=128)


class AuthInvitationValidateView(APIView):
    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_invitation_validate"

    def post(self, request: Request) -> Response:
        if not settings.PREFINERY_INVITATION_DECODER_KEY:
            return Response(
                {"detail": "Invitation decoder key is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = InvitationValidationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = normalize_email(serializer.validated_data["email"])
        invitation_code = serializer.validated_data["invitation_code"]
        valid = invitation_code_matches(
            decoder_key=settings.PREFINERY_INVITATION_DECODER_KEY,
            email=email,
            provided_code=invitation_code,
            shortcode_length=settings.PREFINERY_INVITATION_SHORTCODE_LENGTH,
        )

        if not valid:
            return Response(
                {"valid": False, "detail": "Invitation code is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        InvitationGrant.objects.update_or_create(
            email=email,
            defaults={
                "invitation_code_prefix": invitation_code[: settings.PREFINERY_INVITATION_SHORTCODE_LENGTH],
                "consumed_at": None,
            },
        )
        return Response({"valid": True}, status=status.HTTP_200_OK)


class CheckoutInfoView(APIView):
    """Return the customer email for a completed Polar checkout.

    Used by the signup form to pre-fill the email field without creating
    an InvitationGrant — that only happens when the user submits.
    """

    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_invitation_validate"

    def get(self, request: Request) -> Response:
        checkout_id = request.query_params.get("checkout_id", "").strip()
        use_sandbox = request.query_params.get("sandbox", "0") == "1"

        if not checkout_id:
            return Response(
                {"detail": "checkout_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        polar_api_key = (
            getattr(settings, "POLAR_SANDBOX_API_KEY", "")
            if use_sandbox
            else getattr(settings, "POLAR_API_KEY", "")
        )

        if not polar_api_key:
            return Response(
                {"detail": "Access validation is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            result = validate_checkout(checkout_id, polar_api_key, sandbox=use_sandbox)
        except PolarAccessError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"email": result.email}, status=status.HTTP_200_OK)


class _InviteGateError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class AccessValidateSerializer(Serializer):
    email = EmailField()
    checkout_id = CharField(required=False, allow_blank=True, max_length=256)
    license_key = CharField(required=False, allow_blank=True, max_length=256)
    sandbox = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("checkout_id") and not attrs.get("license_key"):
            raise serializers.ValidationError(
                "Either checkout_id or license_key is required."
            )
        return attrs


class AccessValidateView(APIView):
    """Validate a Polar checkout or license key and create an InvitationGrant.

    Called from the signup form before the user creates their Supabase account.
    On success, the email is allowed through the invite gate on first login.
    """

    authentication_classes: list[type] = []
    permission_classes: list[type] = []
    throttle_classes = [DynamicScopedRateThrottle]
    throttle_scope = "auth_invitation_validate"

    def post(self, request: Request) -> Response:
        polar_api_key = getattr(settings, "POLAR_API_KEY", "")
        polar_org_id = getattr(settings, "POLAR_ORGANIZATION_ID", "")

        if not polar_api_key:
            return Response(
                {"detail": "Access validation is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = AccessValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        checkout_id: str = serializer.validated_data.get("checkout_id", "").strip()
        license_key: str = serializer.validated_data.get("license_key", "").strip()
        provided_email = normalize_email(serializer.validated_data["email"])
        use_sandbox: bool = serializer.validated_data.get("sandbox", False)

        if use_sandbox:
            polar_api_key = getattr(settings, "POLAR_SANDBOX_API_KEY", "")
            polar_org_id = getattr(settings, "POLAR_SANDBOX_ORGANIZATION_ID", "")

        try:
            if checkout_id:
                result = validate_checkout(checkout_id, polar_api_key, sandbox=use_sandbox)
                kind = AccessRedemption.Kind.CHECKOUT
                redemption_id = checkout_id
            else:
                result = validate_license_key(license_key, polar_api_key, polar_org_id, sandbox=use_sandbox)
                kind = AccessRedemption.Kind.LICENSE_KEY
                redemption_id = license_key.strip().upper()
        except PolarAccessError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Email on the Polar order must match what the user typed
        if result.email != provided_email:
            return Response(
                {"detail": "Email does not match the purchase record. "
                           "Please use the email address you used to buy PayGlue."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            # Prevent the same checkout/key from creating two accounts
            if AccessRedemption.objects.filter(redemption_id=redemption_id).exists():
                existing = AccessRedemption.objects.get(redemption_id=redemption_id)
                if existing.email != provided_email:
                    return Response(
                        {"detail": "This access key has already been redeemed."},
                        status=status.HTTP_409_CONFLICT,
                    )
                # Same email retrying — idempotent, just refresh the grant
            else:
                AccessRedemption.objects.create(
                    kind=kind,
                    redemption_id=redemption_id,
                    email=provided_email,
                )

            source = (
                InvitationGrant.Source.POLAR_CHECKOUT
                if kind == AccessRedemption.Kind.CHECKOUT
                else InvitationGrant.Source.POLAR_LICENSE
            )
            InvitationGrant.objects.update_or_create(
                email=provided_email,
                defaults={"source": source, "consumed_at": None},
            )

        return Response({"valid": True}, status=status.HTTP_200_OK)

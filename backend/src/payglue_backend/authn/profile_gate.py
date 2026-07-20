# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Shared invite-gated UserProfile resolution.

Used by both AuthSessionView (the explicit POST /api/v1/auth/session call)
and FirebaseBearerAuthentication (every other authenticated request) so a
brand-new Supabase identity is provisioned a PayGlue profile exactly once,
through the same invite-gate check, no matter which endpoint it first hits.
"""
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status

from payglue_backend.authn.invitations import normalize_email
from payglue_backend.authn.verifier import VerifiedTokenClaims
from payglue_backend.tenants.models import InvitationGrant, UserProfile


class InviteGateError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def resolve_profile_with_invite_gate(claims: VerifiedTokenClaims) -> UserProfile:
    normalized_email = normalize_email(claims.email)

    profile = UserProfile.objects.filter(firebase_uid=claims.firebase_uid).first()
    if profile is not None:
        profile.email = normalized_email
        profile.save(update_fields=["email", "updated_at"])
        return profile

    # Supabase automatically links a new OAuth identity to an existing user
    # when the verified email matches -- in that case the JWT `sub` (our
    # firebase_uid) stays the same as the original account, so this branch
    # is mainly a defensive fallback, not the primary linking mechanism.
    profile = UserProfile.objects.filter(email=normalized_email).first()
    if profile is not None:
        profile.firebase_uid = claims.firebase_uid
        profile.save(update_fields=["firebase_uid", "updated_at"])
        return profile

    if normalized_email in settings.DEV_BYPASS_EMAILS:
        return UserProfile.objects.create(
            firebase_uid=claims.firebase_uid,
            email=normalized_email,
        )

    # A brand-new email always needs an unconsumed InvitationGrant --
    # created by AccessValidateView from a real Creem/Polar purchase, the
    # Creem checkout webhook, or the DEV_BYPASS_LICENSE_KEY test path.
    # There used to be an additional Prefinery-era gate here requiring a
    # PREFINERY_INVITATION_DECODER_KEY to even reach this check; Prefinery
    # isn't used any more (found live, PG-142) and that leftover
    # precondition was silently 503'ing every real signup whenever the key
    # wasn't configured, regardless of whether a valid grant existed.
    with transaction.atomic():
        grant = (
            InvitationGrant.objects.select_for_update()
            .filter(email=normalized_email, consumed_at__isnull=True)
            .first()
        )
        if grant is None:
            raise InviteGateError(
                "An invite code is required before creating an account. "
                "Please sign up with a valid invite code first.",
                status.HTTP_403_FORBIDDEN,
            )

        profile = UserProfile.objects.create(
            firebase_uid=claims.firebase_uid,
            email=normalized_email,
        )
        grant.consumed_at = timezone.now()
        grant.save(update_fields=["consumed_at", "verified_at"])
        return profile

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import logging
import re
from urllib import parse

from django.db import IntegrityError
from django.db.models import Q

logger = logging.getLogger(__name__)
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import SAFE_METHODS
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from payglue_backend.authn.step_up import StepUpError, require_step_up
from payglue_backend.authn.authentication import FirebaseBearerAuthentication
from payglue_backend.authn.rbac import resolve_tenant_membership
from payglue_backend.core.errors import PlanLimitExceededError
from payglue_backend.core.models import TenantContext
from payglue_backend.tenants import support
from payglue_backend.tenants.audit import write_public_audit_event
from datetime import timedelta

from payglue_backend.authn.lifecycle_emails import (
    send_owner_transfer_confirmed_email,
    send_owner_transfer_proposed_email,
    send_owner_transfer_rejected_email,
    send_owner_transfer_request_email,
    send_team_member_removed_emails,
)
from payglue_backend.tenants.models import (
    BillingAccount,
    BillingProfile,
    OwnershipTransferRequest,
    Plan,
    PublicAuditEvent,
    ServicePin,
    Tenant,
    TenantMembership,
    UserProfile,
    StepUpChallenge,
)
from payglue_backend.tenants.plan_limits import check_new_tenant_limit, check_resource_limit
from payglue_backend.tenants.serializers import (
    BillingProfileSerializer,
    ServicePinSerializer,
    SupportRequestSerializer,
    TenantCreateSerializer,
    TenantMembershipSummarySerializer,
    TeamMemberCreateSerializer,
    TeamMemberRoleUpdateSerializer,
    TeamMembershipSerializer,
)

SERVICE_PIN_LIFETIME = timedelta(hours=24)


class HasUserProfile(BasePermission):
    def has_permission(self, request: Request, view: object) -> bool:
        del view
        return getattr(request, "user_profile", None) is not None


class BillingReadBillingAdminOrOwnerWrite(BasePermission):
    def has_permission(self, request: Request, view: object) -> bool:
        del view
        membership = resolve_tenant_membership(request)
        if membership is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        return membership.role in {
            TenantMembership.Role.OWNER,
            TenantMembership.Role.BILLING_ADMIN,
        }


class OwnerOrAdminOnly(BasePermission):
    def has_permission(self, request: Request, view: object) -> bool:
        del view
        membership = resolve_tenant_membership(request)
        if membership is None:
            return False
        return membership.role in {
            TenantMembership.Role.OWNER,
            TenantMembership.Role.ADMIN,
        }


class TenantDetailView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [HasUserProfile]

    def _get_owner_membership(self, request: Request, tenant_slug: str) -> "TenantMembership | None":
        return (
            TenantMembership.objects.filter(
                user_profile=request.user_profile,
                tenant__slug=tenant_slug,
                role=TenantMembership.Role.OWNER,
            )
            .select_related("tenant")
            .first()
        )

    def get(self, request: Request, tenant_slug: str) -> Response:
        membership = (
            TenantMembership.objects.filter(
                user_profile=request.user_profile, tenant__slug=tenant_slug
            )
            .select_related("tenant")
            .first()
        )
        if membership is None:
            return Response(
                {"detail": "Not found or insufficient permissions."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "slug": membership.tenant.slug,
                "webhook_secret": membership.tenant.webhook_secret,
            }
        )

    def patch(self, request: Request, tenant_slug: str) -> Response:
        membership = self._get_owner_membership(request, tenant_slug)
        if membership is None:
            existing = TenantMembership.objects.filter(
                user_profile=request.user_profile, tenant__slug=tenant_slug
            ).values_list("role", flat=True).first()
            if existing:
                return Response(
                    {"detail": f"Insufficient permissions. Your role is '{existing}', owner required."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            return Response(
                {"detail": "Not found or insufficient permissions."},
                status=status.HTTP_404_NOT_FOUND,
            )
        tenant = membership.tenant
        new_slug = request.data.get("slug", tenant.slug)
        if new_slug != tenant.slug:
            if Tenant.objects.filter(slug=new_slug).exclude(pk=tenant.pk).exists():
                return Response({"slug": ["This slug is already taken."]}, status=status.HTTP_400_BAD_REQUEST)
            if not re.match(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", new_slug):
                return Response({"slug": ["Slug must use lowercase letters, numbers, and hyphens."]}, status=status.HTTP_400_BAD_REQUEST)
            Tenant.objects.filter(pk=tenant.pk).update(slug=new_slug, updated_at=timezone.now())
            tenant.slug = new_slug
        return Response({"slug": tenant.slug})

    def delete(self, request: Request, tenant_slug: str) -> Response:
        membership = self._get_owner_membership(request, tenant_slug)
        if membership is None:
            existing = TenantMembership.objects.filter(
                user_profile=request.user_profile, tenant__slug=tenant_slug
            ).values_list("role", flat=True).first()
            if existing:
                return Response(
                    {"detail": f"Insufficient permissions. Your role is '{existing}', owner required."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            return Response(
                {"detail": "Not found or insufficient permissions."},
                status=status.HTTP_404_NOT_FOUND,
            )
        membership.tenant.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TenantSlugCheckView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [HasUserProfile]

    def get(self, request: Request) -> Response:
        slug = request.query_params.get("slug", "").strip()
        if not slug:
            return Response({"available": False, "error": "slug is required"}, status=status.HTTP_400_BAD_REQUEST)
        available = not Tenant.objects.filter(slug=slug).exists()
        return Response({"available": available})


class TenantCollectionView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [HasUserProfile]

    def get(self, request: Request) -> Response:
        memberships = (
            TenantMembership.objects.filter(
                user_profile=request.user_profile,
                tenant__status=Tenant.Status.ACTIVE,
            )
            .select_related("tenant")
            .order_by("tenant__slug")
        )
        serializer = TenantMembershipSummarySerializer(memberships, many=True)
        return Response(serializer.data)

    def post(self, request: Request) -> Response:
        serializer = TenantCreateSerializer(
            data=request.data,
            context={"user_profile": request.user_profile},
        )
        serializer.is_valid(raise_exception=True)

        billing_account = BillingAccount.objects.filter(
            owner=request.user_profile
        ).select_related("plan").first()
        try:
            check_new_tenant_limit(billing_account)
        except PlanLimitExceededError as exc:
            plan_key = billing_account.plan.key if billing_account else None
            return Response(
                {"detail": str(exc), "upgrade_required": True, "plan": plan_key},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        try:
            membership = serializer.save()
        except IntegrityError:
            return Response(
                {"slug": ["Tenant slug already exists."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            TenantMembershipSummarySerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )


class TeamCollectionView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [HasUserProfile]

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> Tenant:
        tenant_ctx = getattr(request, "tenant_ctx", None)
        if (
            not isinstance(tenant_ctx, TenantContext)
            or tenant_ctx.tenant_slug != tenant_slug
        ):
            raise Tenant.DoesNotExist
        return Tenant.objects.get(id=tenant_ctx.tenant_id, slug=tenant_slug)

    def _require_write_membership(self, request: Request) -> TenantMembership | None:
        membership = resolve_tenant_membership(request)
        if membership is None:
            return None
        if membership.role not in {
            TenantMembership.Role.OWNER,
            TenantMembership.Role.ADMIN,
        }:
            return None
        return membership

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if resolve_tenant_membership(request) is None:
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        memberships = TenantMembership.objects.filter(tenant=tenant).select_related(
            "user_profile"
        )
        serializer = TeamMembershipSerializer(memberships, many=True)
        return Response(serializer.data)

    def post(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        actor_membership = self._require_write_membership(request)
        if actor_membership is None:
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        serializer = TeamMemberCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data.get("email")
        firebase_uid = serializer.validated_data.get("firebase_uid")
        requested_role = serializer.validated_data["role"]

        # PG-182: exactly one owner per tenant -- a member is never added as
        # owner. Ownership only moves via the confirmed transfer flow.
        if requested_role == TenantMembership.Role.OWNER:
            return Response(
                {"detail": "A member cannot be added as owner; use the ownership-transfer flow."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invited_new_account = False

        if email and firebase_uid:
            firebase_uid_str = str(firebase_uid)
            email_str = str(email)
            uid_profile = UserProfile.objects.filter(
                firebase_uid=firebase_uid_str
            ).first()
            email_profile = UserProfile.objects.filter(email=email_str).first()

            if uid_profile and email_profile and uid_profile.id != email_profile.id:
                return Response(
                    {"detail": "firebase_uid/email mismatch."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if uid_profile is not None:
                if uid_profile.email != email_str:
                    return Response(
                        {"detail": "firebase_uid/email mismatch."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                user_profile = uid_profile
            elif email_profile is not None:
                if email_profile.firebase_uid != firebase_uid_str:
                    return Response(
                        {"detail": "firebase_uid/email mismatch."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                user_profile = email_profile
            else:
                return Response(
                    {"detail": "User profile for email/firebase_uid was not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif email:
            email_str = str(email)
            user_profile = UserProfile.objects.filter(email=email_str).first()
            if user_profile is None:
                # No PayGlue account for this email yet -- this person isn't
                # self-signing-up through a Creem checkout (that's a separate,
                # paying flow), they're being added as a sub-user under this
                # tenant's existing plan by an owner/admin. Provision them
                # directly: a Supabase Auth account + PayGlue's own
                # UserProfile, and let Supabase's invite email (magic link)
                # handle the login side.
                #
                # Check the plan limit first -- they can't already be a
                # member (they had no UserProfile a moment ago), so this
                # will always result in one new membership if it succeeds.
                # Checking after inviting would mean sending a real invite
                # email and creating a Supabase account for an operation
                # that's about to fail anyway.
                try:
                    check_resource_limit(tenant, "team members")
                except PlanLimitExceededError as exc:
                    plan_key = tenant.billing_account.plan.key if tenant.billing_account else None
                    return Response(
                        {"detail": str(exc), "upgrade_required": True, "plan": plan_key},
                        status=status.HTTP_402_PAYMENT_REQUIRED,
                    )

                from payglue_backend.tenants.supabase_admin import (
                    SupabaseAdminError,
                    invite_supabase_user,
                )

                try:
                    supabase_user_id = invite_supabase_user(email_str)
                except SupabaseAdminError as exc:
                    # Cloudflare replaces any 502 from the origin with its own
                    # generic "origin is overloaded or misconfigured" interstitial
                    # regardless of body, so the real reason (e.g. Supabase
                    # rejecting an invalid/undeliverable invitee address) never
                    # reaches the user -- they just see an opaque error and can't
                    # add anyone. 400 is a real client-facing status Cloudflare
                    # passes through, so the actual message shows. Same lesson as
                    # the Creem cancel path below.
                    logger.warning("Supabase invite failed for %s: %s", email_str, exc)
                    return Response(
                        {"detail": f"Could not invite {email_str}: {exc}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                invited_new_account = True
                user_profile, _ = UserProfile.objects.get_or_create(
                    firebase_uid=supabase_user_id, defaults={"email": email_str}
                )
        else:
            user_profile = UserProfile.objects.filter(
                firebase_uid=str(firebase_uid)
            ).first()
            if user_profile is None:
                return Response(
                    {"detail": "User profile for firebase_uid was not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        already_member = TenantMembership.objects.filter(
            tenant=tenant, user_profile=user_profile
        ).exists()
        if not already_member:
            try:
                check_resource_limit(tenant, "team members")
            except PlanLimitExceededError as exc:
                plan_key = tenant.billing_account.plan.key if tenant.billing_account else None
                return Response(
                    {"detail": str(exc), "upgrade_required": True, "plan": plan_key},
                    status=status.HTTP_402_PAYMENT_REQUIRED,
                )

        membership, created = TenantMembership.objects.get_or_create(
            tenant=tenant,
            user_profile=user_profile,
            defaults={"role": requested_role},
        )
        if not created:
            return Response(
                {"detail": "Membership already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        write_public_audit_event(
            tenant=tenant,
            actor_membership=actor_membership,
            event_type=PublicAuditEvent.EventType.TEAM_MEMBER_CREATED,
            target_type="membership",
            target_id=str(membership.id),
            metadata={
                "role": membership.role,
                "user_profile_id": membership.user_profile_id,
            },
        )
        response_data = TeamMembershipSerializer(membership).data
        response_data["invited_new_account"] = invited_new_account
        return Response(response_data, status=status.HTTP_201_CREATED)


class TeamMembershipDetailView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [HasUserProfile]

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> Tenant:
        tenant_ctx = getattr(request, "tenant_ctx", None)
        if (
            not isinstance(tenant_ctx, TenantContext)
            or tenant_ctx.tenant_slug != tenant_slug
        ):
            raise Tenant.DoesNotExist
        return Tenant.objects.get(id=tenant_ctx.tenant_id, slug=tenant_slug)

    def _require_write_membership(self, request: Request) -> TenantMembership | None:
        membership = resolve_tenant_membership(request)
        if membership is None:
            return None
        if membership.role not in {
            TenantMembership.Role.OWNER,
            TenantMembership.Role.ADMIN,
        }:
            return None
        return membership

    def _owner_count(self, tenant: Tenant) -> int:
        return TenantMembership.objects.filter(
            tenant=tenant,
            role=TenantMembership.Role.OWNER,
        ).count()

    def patch(self, request: Request, tenant_slug: str, membership_id: int) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        actor_membership = self._require_write_membership(request)
        if actor_membership is None:
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        serializer = TeamMemberRoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_role = serializer.validated_data["role"]
        # PG-182: exactly one owner per tenant. Promoting someone to owner is
        # not a direct role edit -- it goes through the confirmed ownership
        # transfer flow (the current owner must approve it).
        if new_role == TenantMembership.Role.OWNER:
            return Response(
                {"detail": "Ownership changes go through the ownership-transfer flow."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            membership = (
                TenantMembership.objects.select_for_update()
                .filter(
                    id=membership_id,
                    tenant=tenant,
                )
                .select_related("user_profile")
                .first()
            )
            if membership is None:
                return Response(
                    {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
                )

            if (
                actor_membership.role == TenantMembership.Role.ADMIN
                and new_role == TenantMembership.Role.OWNER
            ):
                return Response(
                    {"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN
                )

            if (
                actor_membership.role == TenantMembership.Role.ADMIN
                and membership.role == TenantMembership.Role.OWNER
            ):
                return Response(
                    {"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN
                )

            if membership.role == TenantMembership.Role.OWNER:
                owner_count = (
                    TenantMembership.objects.select_for_update()
                    .filter(
                        tenant=tenant,
                        role=TenantMembership.Role.OWNER,
                    )
                    .count()
                )
                if new_role != TenantMembership.Role.OWNER and owner_count <= 1:
                    return Response(
                        {"detail": "Cannot demote the last owner."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            membership.role = new_role
            membership.save(update_fields=["role", "updated_at"])
        write_public_audit_event(
            tenant=tenant,
            actor_membership=actor_membership,
            event_type=PublicAuditEvent.EventType.TEAM_MEMBER_ROLE_UPDATED,
            target_type="membership",
            target_id=str(membership.id),
            metadata={"role": membership.role},
        )
        return Response(TeamMembershipSerializer(membership).data)

    def delete(
        self, request: Request, tenant_slug: str, membership_id: int
    ) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        actor_membership = self._require_write_membership(request)
        if actor_membership is None:
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            membership = (
                TenantMembership.objects.select_for_update()
                .filter(id=membership_id, tenant=tenant)
                .first()
            )
            if membership is None:
                return Response(
                    {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
                )

            if (
                actor_membership.role == TenantMembership.Role.ADMIN
                and membership.role == TenantMembership.Role.OWNER
            ):
                return Response(
                    {"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN
                )

            if membership.role == TenantMembership.Role.OWNER:
                owner_count = (
                    TenantMembership.objects.select_for_update()
                    .filter(
                        tenant=tenant,
                        role=TenantMembership.Role.OWNER,
                    )
                    .count()
                )
                if owner_count <= 1:
                    return Response(
                        {"detail": "Cannot remove the last owner."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            removed_id = str(membership.id)
            # Read before the delete: afterwards the row, and with it the
            # address we have to write to, is gone.
            removed_email = membership.user_profile.email
            removed_role = membership.get_role_display()
            # Every owner, so a removal cannot be hidden from the people
            # answerable for the publication, plus whoever performed it (an
            # admin is not necessarily an owner). Collected inside the
            # transaction so a concurrent change cannot skip a recipient.
            notice_recipients = list(
                TenantMembership.objects.filter(
                    tenant=tenant, role=TenantMembership.Role.OWNER
                )
                .exclude(id=membership.id)
                .values_list("user_profile__email", flat=True)
            )
            notice_recipients.append(actor_membership.user_profile.email)
            membership.delete()
        write_public_audit_event(
            tenant=tenant,
            actor_membership=actor_membership,
            event_type=PublicAuditEvent.EventType.TEAM_MEMBER_REMOVED,
            target_type="membership",
            target_id=removed_id,
            metadata={},
        )
        # After the commit: the removal is the fact, the mail is the receipt.
        # Sending inside the transaction would risk mailing about something a
        # later rollback undid.
        send_team_member_removed_emails(
            removed_email=removed_email,
            removed_role=removed_role,
            actor_email=actor_membership.user_profile.email,
            tenant_slug=tenant.slug,
            notice_recipients=notice_recipients,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class _TenantContextMixin:
    def _require_tenant_context(self, request: Request, tenant_slug: str) -> Tenant:
        tenant_ctx = getattr(request, "tenant_ctx", None)
        if (
            not isinstance(tenant_ctx, TenantContext)
            or tenant_ctx.tenant_slug != tenant_slug
        ):
            raise Tenant.DoesNotExist
        return Tenant.objects.get(id=tenant_ctx.tenant_id, slug=tenant_slug)


def _serialize_transfer(tr: OwnershipTransferRequest | None) -> dict | None:
    if tr is None:
        return None
    return {
        "id": tr.id,
        "status": tr.status,
        "current_owner_email": tr.current_owner.email,
        "new_owner_email": tr.new_owner.email,
        "requested_by_email": tr.requested_by.email,
        "created_at": tr.created_at.isoformat(),
    }


class OwnershipTransferView(_TenantContextMixin, APIView):
    """PG-182: GET the tenant's pending ownership transfer (if any); POST to
    request one. Requesting is allowed for owners and admins; the current
    owner alone confirms/rejects it (see OwnershipTransferActionView)."""

    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [HasUserProfile]

    def _pending(self, tenant: Tenant) -> OwnershipTransferRequest | None:
        return (
            OwnershipTransferRequest.objects.filter(
                tenant=tenant, status=OwnershipTransferRequest.Status.PENDING
            )
            .select_related("current_owner", "new_owner", "requested_by")
            .first()
        )

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if resolve_tenant_membership(request) is None:
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
        return Response({"pending": _serialize_transfer(self._pending(tenant))})

    def post(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        actor = resolve_tenant_membership(request)
        if actor is None or actor.role not in {
            TenantMembership.Role.OWNER,
            TenantMembership.Role.ADMIN,
        }:
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        membership_id = request.data.get("new_owner_membership_id")
        if not membership_id:
            return Response(
                {"detail": "new_owner_membership_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            target = (
                TenantMembership.objects.select_for_update()
                .filter(id=membership_id, tenant=tenant)
                .select_related("user_profile")
                .first()
            )
            if target is None:
                return Response({"detail": "Member not found."}, status=status.HTTP_404_NOT_FOUND)
            if target.role == TenantMembership.Role.OWNER:
                return Response(
                    {"detail": "That member is already the owner."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            owner_m = (
                TenantMembership.objects.select_for_update()
                .filter(tenant=tenant, role=TenantMembership.Role.OWNER)
                .select_related("user_profile")
                .first()
            )
            if owner_m is None:
                return Response(
                    {"detail": "This tenant has no owner."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if OwnershipTransferRequest.objects.filter(
                tenant=tenant, status=OwnershipTransferRequest.Status.PENDING
            ).exists():
                return Response(
                    {"detail": "An ownership transfer is already pending."},
                    status=status.HTTP_409_CONFLICT,
                )
            transfer = OwnershipTransferRequest.objects.create(
                tenant=tenant,
                current_owner=owner_m.user_profile,
                new_owner=target.user_profile,
                requested_by=actor.user_profile,
            )

        send_owner_transfer_request_email(
            owner_m.user_profile.email, target.user_profile.email, tenant.slug
        )
        # The proposed owner is told separately that they were nominated -- the
        # mail above is the current owner's confirm/reject decision and must not
        # go to the person the publication would move to.
        send_owner_transfer_proposed_email(
            owner_m.user_profile.email, target.user_profile.email, tenant.slug
        )
        write_public_audit_event(
            tenant=tenant,
            actor_membership=actor,
            event_type=PublicAuditEvent.EventType.OWNERSHIP_TRANSFER_REQUESTED,
            target_type="ownership_transfer",
            target_id=str(transfer.id),
            metadata={"new_owner": target.user_profile.email},
        )
        return Response(_serialize_transfer(transfer), status=status.HTTP_201_CREATED)


class OwnershipTransferActionView(_TenantContextMixin, APIView):
    """PG-182: confirm / reject / cancel the pending ownership transfer.
    confirm and reject are the CURRENT owner's decision only; cancel can be
    done by the requester or any owner/admin. On confirm the new member becomes
    owner and the old owner becomes billing_admin (billing stays with them)."""

    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [HasUserProfile]

    def post(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        actor = resolve_tenant_membership(request)
        if actor is None:
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        action = request.data.get("action")
        if action not in {"confirm", "reject", "cancel"}:
            return Response(
                {"detail": "action must be confirm, reject or cancel."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # PG-203: only "confirm" needs re-confirmation. Reject and cancel leave
        # everything as it was, so a code prompt there would be friction that
        # buys nothing. Checked here rather than in the frontend dialog: a
        # confirmation the client can skip by calling the API directly is not a
        # control. Outside the transaction so the grant write does not happen
        # while the transfer rows are locked.
        if action == "confirm":
            try:
                require_step_up(
                    request, request.user_profile, StepUpChallenge.Purpose.OWNER_TRANSFER
                )
            except StepUpError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            transfer = (
                OwnershipTransferRequest.objects.select_for_update()
                .filter(tenant=tenant, status=OwnershipTransferRequest.Status.PENDING)
                .select_related("current_owner", "new_owner", "requested_by")
                .first()
            )
            if transfer is None:
                return Response(
                    {"detail": "No pending ownership transfer."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            is_current_owner = request.user_profile.id == transfer.current_owner_id

            if action in {"confirm", "reject"} and not is_current_owner:
                return Response(
                    {"detail": "Only the current owner can confirm or reject the transfer."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if action == "cancel" and not (
                actor.role in {TenantMembership.Role.OWNER, TenantMembership.Role.ADMIN}
                or request.user_profile.id == transfer.requested_by_id
            ):
                return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

            if action == "confirm":
                new_owner_m = (
                    TenantMembership.objects.select_for_update()
                    .filter(tenant=tenant, user_profile=transfer.new_owner)
                    .first()
                )
                old_owner_m = (
                    TenantMembership.objects.select_for_update()
                    .filter(tenant=tenant, user_profile=transfer.current_owner)
                    .first()
                )
                if new_owner_m is None or old_owner_m is None:
                    return Response(
                        {"detail": "A member in this transfer is no longer in the team."},
                        status=status.HTTP_409_CONFLICT,
                    )
                old_owner_m.role = TenantMembership.Role.BILLING_ADMIN
                old_owner_m.save(update_fields=["role", "updated_at"])
                new_owner_m.role = TenantMembership.Role.OWNER
                new_owner_m.save(update_fields=["role", "updated_at"])
                transfer.status = OwnershipTransferRequest.Status.CONFIRMED
            elif action == "reject":
                transfer.status = OwnershipTransferRequest.Status.REJECTED
            else:
                transfer.status = OwnershipTransferRequest.Status.CANCELLED
            transfer.resolved_at = timezone.now()
            transfer.save(update_fields=["status", "resolved_at"])

        # Everyone involved hears how it ended, including whoever just clicked:
        # an ownership change is security-relevant, so a receipt is the point.
        # Duplicates are collapsed downstream (one person can be two parties).
        parties = [
            transfer.current_owner.email,
            transfer.new_owner.email,
            transfer.requested_by.email,
        ]
        if action == "confirm":
            send_owner_transfer_confirmed_email(
                transfer.current_owner.email, transfer.new_owner.email, tenant.slug, parties
            )
        else:
            # reject and cancel look identical from the outside: nothing changed.
            send_owner_transfer_rejected_email(
                transfer.current_owner.email, transfer.new_owner.email, tenant.slug, parties
            )

        event_type = {
            "confirm": PublicAuditEvent.EventType.OWNERSHIP_TRANSFER_CONFIRMED,
            "reject": PublicAuditEvent.EventType.OWNERSHIP_TRANSFER_REJECTED,
            "cancel": PublicAuditEvent.EventType.OWNERSHIP_TRANSFER_REJECTED,
        }[action]
        write_public_audit_event(
            tenant=tenant,
            actor_membership=actor,
            event_type=event_type,
            target_type="ownership_transfer",
            target_id=str(transfer.id),
            metadata={"action": action, "new_owner": transfer.new_owner.email},
        )
        return Response(_serialize_transfer(transfer))


class BillingProfileView(_TenantContextMixin, APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [BillingReadBillingAdminOrOwnerWrite]

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        profile, _ = BillingProfile.objects.get_or_create(tenant=tenant)
        return Response(BillingProfileSerializer(profile).data)

    def put(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        allowed_fields = {"legal_name", "billing_email", "country_code", "tax_id"}
        unknown_fields = sorted(set(request.data.keys()) - allowed_fields)
        if unknown_fields:
            return Response(
                {"detail": f"Unknown fields: {', '.join(unknown_fields)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile, _ = BillingProfile.objects.get_or_create(tenant=tenant)
        serializer = BillingProfileSerializer(instance=profile, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        write_public_audit_event(
            tenant=tenant,
            actor_membership=resolve_tenant_membership(request),
            event_type=PublicAuditEvent.EventType.BILLING_PROFILE_UPDATED,
            target_type="billing_profile",
            target_id=str(profile.id),
            metadata={"updated_fields": sorted(serializer.validated_data.keys())},
        )
        return Response(serializer.data)


class ServicePinView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [OwnerOrAdminOnly]

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> Tenant:
        tenant_ctx = getattr(request, "tenant_ctx", None)
        if (
            not isinstance(tenant_ctx, TenantContext)
            or tenant_ctx.tenant_slug != tenant_slug
        ):
            raise Tenant.DoesNotExist
        return Tenant.objects.get(id=tenant_ctx.tenant_id, slug=tenant_slug)

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        active_pin = (
            ServicePin.objects.filter(
                tenant=tenant, revoked_at__isnull=True, expires_at__gt=timezone.now()
            )
            .order_by("-created_at")
            .first()
        )
        if active_pin is None:
            return Response({"pin": None})
        return Response({"pin": ServicePinSerializer(active_pin).data})

    def post(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        with transaction.atomic():
            ServicePin.objects.filter(
                tenant=tenant, revoked_at__isnull=True, expires_at__gt=now
            ).update(revoked_at=now)

            for _attempt in range(5):
                try:
                    pin = ServicePin.objects.create(
                        tenant=tenant,
                        created_by=resolve_tenant_membership(request),
                        expires_at=now + SERVICE_PIN_LIFETIME,
                    )
                    break
                except IntegrityError:
                    continue
            else:
                return Response(
                    {"detail": "Could not generate a unique service PIN, try again."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        write_public_audit_event(
            tenant=tenant,
            actor_membership=resolve_tenant_membership(request),
            event_type=PublicAuditEvent.EventType.SERVICE_PIN_GENERATED,
            target_type="service_pin",
            target_id=str(pin.id),
        )
        return Response({"pin": ServicePinSerializer(pin).data}, status=status.HTTP_201_CREATED)

    def delete(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        active_pins = ServicePin.objects.filter(
            tenant=tenant, revoked_at__isnull=True, expires_at__gt=now
        )
        revoked_ids = list(active_pins.values_list("id", flat=True))
        active_pins.update(revoked_at=now)

        if revoked_ids:
            write_public_audit_event(
                tenant=tenant,
                actor_membership=resolve_tenant_membership(request),
                event_type=PublicAuditEvent.EventType.SERVICE_PIN_REVOKED,
                target_type="service_pin",
                target_id=",".join(str(i) for i in revoked_ids),
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class _PolarBaseMixin:
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [BillingReadBillingAdminOrOwnerWrite]

    def _require_tenant_context(self, request: Request, tenant_slug: str) -> "Tenant":
        tenant_ctx = getattr(request, "tenant_ctx", None)
        if (
            not isinstance(tenant_ctx, TenantContext)
            or tenant_ctx.tenant_slug != tenant_slug
        ):
            raise Tenant.DoesNotExist
        return Tenant.objects.get(id=tenant_ctx.tenant_id, slug=tenant_slug)


class TenantUsageView(_PolarBaseMixin, APIView):
    """Per-resource usage vs. the tenant's billing plan, for the dashboard
    usage cards (GOGU-138)."""

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.webhooks.models import BuyButton, IntegrationConfig, PaywallConfig, PricingTable

        billing_account = tenant.billing_account
        plan = billing_account.plan if billing_account else None

        def usage(used: int, limit: int | None) -> dict:
            return {"used": used, "limit": limit}

        publications_used = (
            Tenant.objects.filter(billing_account=billing_account).count()
            if billing_account
            else 1
        )

        return Response({
            "plan": plan.key if plan else None,
            # PG-183: tester accounts (redeemed a PayGlue license code) have no
            # Creem subscription, so the billing screen shows a "Tester" state
            # plus the access-window expiry instead of an empty subscription.
            "is_tester": bool(billing_account and billing_account.is_tester),
            "tester_access_expires_at": (
                billing_account.tester_access_expires_at.isoformat()
                if billing_account and billing_account.tester_access_expires_at
                else None
            ),
            # PG-210: the dashboard used to say "locked in for life at your
            # original rate" without ever naming the rate, because nothing on
            # the account knew it. These two are that number.
            "founding_tier": billing_account.founding_tier if billing_account else None,
            "founding_monthly_eur": (
                billing_account.founding_price_cents // 100
                if billing_account and billing_account.founding_price_cents
                else None
            ),
            "usage": {
                "publications": usage(publications_used, plan.max_tenants if plan else None),
                "buy_buttons": usage(
                    BuyButton.objects.filter(tenant_slug=tenant_slug).count(),
                    plan.max_buy_buttons_per_tenant if plan else None,
                ),
                "paywalls": usage(
                    PaywallConfig.objects.filter(tenant_slug=tenant_slug).count(),
                    plan.max_paywalls_per_tenant if plan else None,
                ),
                "pricing_tables": usage(
                    PricingTable.objects.filter(tenant_slug=tenant_slug).count(),
                    plan.max_pricing_tables_per_tenant if plan else None,
                ),
                "providers": usage(
                    IntegrationConfig.objects.filter(tenant_slug=tenant_slug)
                    .exclude(provider_key="cms")
                    .count(),
                    plan.max_providers_per_tenant if plan else None,
                ),
                "team_members": usage(
                    TenantMembership.objects.filter(tenant=tenant).count(),
                    plan.max_team_members_per_tenant if plan else None,
                ),
            },
        })


def _polar_fetch_subscriptions(email: str, api_key: str, base_url: str, sandbox: bool) -> list:
    from payglue_backend.authn.polar_access import _get, PolarAccessError
    try:
        data = _get(f"{base_url}/v1/subscriptions?customer_email={email}&limit=10", api_key)
        items = data.get("items", [])
        if sandbox:
            for item in items:
                item["_sandbox"] = True
        return items
    except PolarAccessError:
        return []


def _polar_fetch_orders(email: str, api_key: str, base_url: str, sandbox: bool) -> list:
    from payglue_backend.authn.polar_access import _get, PolarAccessError
    try:
        data = _get(f"{base_url}/v1/orders?customer_email={email}&limit=25", api_key)
        items = data.get("items", [])
        if sandbox:
            for item in items:
                item["_sandbox"] = True
        return items
    except PolarAccessError:
        return []


class PolarSubscriptionView(_PolarBaseMixin, APIView):
    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from django.conf import settings
        from payglue_backend.authn.polar_access import POLAR_API_BASE, POLAR_SANDBOX_API_BASE

        email = request.user_profile.email
        subscriptions: list = []

        if settings.POLAR_API_KEY:
            subscriptions += _polar_fetch_subscriptions(email, settings.POLAR_API_KEY, POLAR_API_BASE, sandbox=False)

        if settings.POLAR_SANDBOX_API_KEY:
            subscriptions += _polar_fetch_subscriptions(email, settings.POLAR_SANDBOX_API_KEY, POLAR_SANDBOX_API_BASE, sandbox=True)

        return Response({"subscriptions": subscriptions})

    def post(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        subscription_id = request.data.get("subscription_id")
        if not subscription_id:
            return Response(
                {"detail": "subscription_id required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.conf import settings
        from payglue_backend.authn.polar_access import _patch, PolarAccessError, POLAR_API_BASE, POLAR_SANDBOX_API_BASE

        use_sandbox = bool(request.data.get("sandbox", False))
        if use_sandbox:
            api_key = settings.POLAR_SANDBOX_API_KEY
            base_url = POLAR_SANDBOX_API_BASE
        else:
            api_key = settings.POLAR_API_KEY
            base_url = POLAR_API_BASE

        if not api_key:
            return Response({"detail": "Polar API key not configured."}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            data = _patch(
                f"{base_url}/v1/subscriptions/{subscription_id}",
                api_key,
                {"cancel_at_period_end": True},
            )
        except PolarAccessError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(data)


class PolarInvoicesView(_PolarBaseMixin, APIView):
    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from django.conf import settings
        from payglue_backend.authn.polar_access import POLAR_API_BASE, POLAR_SANDBOX_API_BASE

        email = request.user_profile.email
        invoices: list = []

        if settings.POLAR_API_KEY:
            invoices += _polar_fetch_orders(email, settings.POLAR_API_KEY, POLAR_API_BASE, sandbox=False)

        if settings.POLAR_SANDBOX_API_KEY:
            invoices += _polar_fetch_orders(email, settings.POLAR_SANDBOX_API_KEY, POLAR_SANDBOX_API_BASE, sandbox=True)

        invoices.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return Response({"invoices": invoices})


def _creem_item_belongs_to_customer(item: dict, customer_id: str) -> bool:
    customer = item.get("customer")
    item_customer_id = customer.get("id") if isinstance(customer, dict) else customer
    return item_customer_id == customer_id


def _creem_fetch_subscription_by_id(subscription_id: str, api_key: str, base_url: str, sandbox: bool) -> dict | None:
    """Fetch one subscription directly by ID -- reliable, unlike
    /v1/subscriptions/search (PG-147/PG-149: no customer_id filter, only
    one unfiltered page, so a real subscription can simply not be on it).
    Only usable once BillingAccount.creem_subscription_id is populated,
    which the checkout.completed webhook now sets on every dashboard
    upgrade (PG-142) -- older/legacy accounts fall back to the search."""
    from payglue_backend.authn.creem_access import CreemAccessError, _get
    try:
        data = _get(f"{base_url}/v1/subscriptions?subscription_id={subscription_id}", api_key)
    except CreemAccessError:
        return None
    if sandbox:
        data["_sandbox"] = True
    return data


def _creem_fetch_subscriptions(customer_id: str, api_key: str, base_url: str, sandbox: bool) -> list:
    from payglue_backend.authn.creem_access import CreemAccessError, _get
    try:
        # /v1/subscriptions/search has no customer_id query param (verified
        # against Creem's OpenAPI spec, PG-147) -- it silently ignores the
        # one we pass and returns a page of ALL subscriptions across the
        # whole PayGlue Creem account. Filter client-side or every viewer
        # sees other customers' billing data.
        #
        # Tried adding &customer={customer_id} too (Creem's CLI takes
        # --customer <id>, so it seemed like the real param name) -- found
        # live it made things *worse*: a real Studio subscription that the
        # customer_id-only query at least sometimes surfaced came back
        # completely empty with both params combined. Reverted; this
        # endpoint's real filtering behavior is still unverified (PG-147),
        # don't guess at it again without a confirmed response to compare
        # against.
        data = _get(f"{base_url}/v1/subscriptions/search?customer_id={customer_id}", api_key)
        items = [
            item for item in data.get("items", [])
            if _creem_item_belongs_to_customer(item, customer_id)
        ]
        if sandbox:
            for item in items:
                item["_sandbox"] = True
        return items
    except CreemAccessError:
        return []


def _creem_fetch_transactions(customer_id: str, api_key: str, base_url: str, sandbox: bool) -> list:
    from payglue_backend.authn.creem_access import CreemAccessError, _get

    # Page 1 -- unchanged, confirmed-working request. Found live: with
    # enough transactions across the whole PayGlue Creem account, a real,
    # older transaction for this customer can simply not be on it
    # (PG-147/PG-149's "single unfiltered page" issue). Rather than modify
    # this call itself again after the &customer= attempt made things
    # *worse* live, page 2+ are ADDITIVE, best-effort requests merged in --
    # if the "page" param name/pagination style guessed here is wrong, the
    # extra calls just return nothing new or error (caught), and page 1's
    # already-working results are untouched either way.
    try:
        data = _get(f"{base_url}/v1/transactions/search?customer_id={customer_id}", api_key)
    except CreemAccessError:
        return []

    items = list(data.get("items", []))
    seen_ids = {item.get("id") for item in items}
    for page in range(2, 6):
        try:
            page_data = _get(
                f"{base_url}/v1/transactions/search?customer_id={customer_id}&page={page}", api_key
            )
        except CreemAccessError:
            break
        page_items = page_data.get("items", [])
        if not page_items:
            break
        new_items = [item for item in page_items if item.get("id") not in seen_ids]
        if not new_items:
            break
        items.extend(new_items)
        seen_ids.update(item.get("id") for item in new_items)

    filtered = [item for item in items if _creem_item_belongs_to_customer(item, customer_id)]
    if sandbox:
        for item in filtered:
            item["_sandbox"] = True
    return filtered


def _creem_customer_slots(email: str) -> list[tuple[str, str, str, bool]]:
    """For each configured Creem API key (live, sandbox) that has a customer
    matching `email`, returns (customer_id, api_key, base_url, sandbox)."""
    from django.conf import settings
    from payglue_backend.authn.creem_access import (
        CREEM_API_BASE,
        CREEM_TEST_API_BASE,
        resolve_customer_id_by_email,
    )

    slots: list[tuple[str, str, str, bool]] = []
    for api_key, base_url, sandbox in (
        (settings.CREEM_API_KEY, CREEM_API_BASE, False),
        (settings.CREEM_SANDBOX_API_KEY, CREEM_TEST_API_BASE, True),
    ):
        if not api_key:
            continue
        customer_id = resolve_customer_id_by_email(email, api_key, sandbox=sandbox)
        if customer_id:
            slots.append((customer_id, api_key, base_url, sandbox))
    return slots


def _creem_current_subscription_id(user_profile: UserProfile) -> str | None:
    """Best-effort ID of the user's currently active Creem subscription, if
    any -- used to tag a new dashboard-upgrade checkout so the webhook can
    cancel this old subscription once the new one is confirmed (PG-150
    follow-up: switching plans must not leave the old subscription running
    and billing in parallel with the new one).

    Found live: BillingAccount.creem_subscription_id only ever tracks the
    MOST RECENTLY purchased subscription, not necessarily a still-active
    one -- once that one gets cancelled (e.g. via the Danger Zone), the
    direct lookup keeps returning it (now dead) instead of falling through
    to the search that would find an older, still-active subscription
    predating PG-142 (never recorded at all). Must check status here, not
    just "was something found by ID"."""
    direct = _creem_active_subscription_for_user(user_profile)
    if direct is not None:
        sub, *_rest = direct
        if sub.get("status") in {"active", "trialing"}:
            subscription_id = sub.get("id")
            return str(subscription_id) if subscription_id else None

    for customer_id, api_key, base_url, sandbox in _creem_customer_slots(user_profile.email):
        for sub in _creem_fetch_subscriptions(customer_id, api_key, base_url, sandbox):
            if sub.get("status") in {"active", "trialing"}:
                subscription_id = sub.get("id")
                return str(subscription_id) if subscription_id else None
    return None


def _creem_active_subscription_for_user(user_profile: UserProfile) -> tuple[dict, str, str, bool] | None:
    """Preferred lookup: fetch the user's subscription directly by the ID
    stored on their BillingAccount (set by the checkout.completed webhook,
    PG-142), instead of the unreliable unfiltered/paginated search. Returns
    (subscription, api_key, base_url, sandbox), or None if there's no
    stored subscription_id yet (legacy accounts) or the lookup fails."""
    from django.conf import settings
    from payglue_backend.authn.creem_access import CREEM_API_BASE, CREEM_TEST_API_BASE

    billing_account = getattr(user_profile, "billing_account", None)
    subscription_id = getattr(billing_account, "creem_subscription_id", "") if billing_account else ""
    if not subscription_id:
        return None

    for api_key, base_url, sandbox in (
        (settings.CREEM_API_KEY, CREEM_API_BASE, False),
        (settings.CREEM_SANDBOX_API_KEY, CREEM_TEST_API_BASE, True),
    ):
        if not api_key:
            continue
        sub = _creem_fetch_subscription_by_id(subscription_id, api_key, base_url, sandbox)
        if sub:
            return sub, api_key, base_url, sandbox
    return None


def _creem_raw_subscription_status(account: BillingAccount) -> str | None:
    """PG-190: unlike _creem_active_subscription_for_user, does NOT filter
    for active/trialing -- returns whatever raw status Creem reports for
    this account's stored subscription id, including terminal values like
    "canceled". Used only once _creem_subscription_for_switch has already
    stopped finding an active/trialing subscription for this account, to
    tell a confirmed cancellation apart from an ambiguous one (payment
    retry, temporary Creem-side pause, or the fetch itself failing --
    _creem_fetch_subscription_by_id collapses all of those to None the same
    way it collapses a genuine 404). Returns None on any failure -- callers
    must treat that as "unclear", never as "confirmed canceled"."""
    from django.conf import settings
    from payglue_backend.authn.creem_access import CREEM_API_BASE, CREEM_TEST_API_BASE

    subscription_id = account.creem_subscription_id
    if not subscription_id:
        return None

    for api_key, base_url, sandbox in (
        (settings.CREEM_API_KEY, CREEM_API_BASE, False),
        (settings.CREEM_SANDBOX_API_KEY, CREEM_TEST_API_BASE, True),
    ):
        if not api_key:
            continue
        sub = _creem_fetch_subscription_by_id(subscription_id, api_key, base_url, sandbox)
        if sub:
            status = sub.get("status")
            return str(status) if status else None
    return None


def _creem_subscription_for_switch(user_profile: UserProfile) -> tuple[dict, str, str, bool] | None:
    """Like _creem_active_subscription_for_user, but also falls back to the
    email-based search when BillingAccount.creem_subscription_id isn't
    populated yet.

    Found live (PG-141 test): a customer's very first Creem purchase never
    goes through the dashboard_upgrade webhook branch that sets
    creem_subscription_id -- only a later in-dashboard switch does. Without
    this fallback, that first switch wrongly concluded "no existing
    subscription" and created a second, parallel checkout instead of
    swapping in place, leaving both subscriptions alive and un-cancelled
    (the search-based safety net in _creem_current_subscription_id can miss
    it too -- see its docstring, PG-147/PG-149).

    Also falls through when the direct-by-ID result exists but is no longer
    active/trialing (e.g. cancelled via the Danger Zone) -- same "stale
    stored ID" case _creem_current_subscription_id already guards against.

    Found live (PG-141 test): the search fallback itself can come back
    completely empty for a real, active subscription -- not just wrong-page,
    genuinely zero results -- exactly the failure mode PG-147/PG-149's
    docstring already warned about. /v1/transactions/search is reliably
    customer-scoped (also confirmed live, PG-149 -- see BillingView.vue's
    recurringSource): a recurring transaction carries the subscription's id,
    which can then be fetched directly and reliably by id."""
    direct = _creem_active_subscription_for_user(user_profile)
    if direct is not None:
        sub, *_rest = direct
        if sub.get("status") in {"active", "trialing"}:
            return direct

    for customer_id, api_key, base_url, sandbox in _creem_customer_slots(user_profile.email):
        for sub in _creem_fetch_subscriptions(customer_id, api_key, base_url, sandbox):
            if sub.get("status") in {"active", "trialing"}:
                return sub, api_key, base_url, sandbox

    for customer_id, api_key, base_url, sandbox in _creem_customer_slots(user_profile.email):
        for txn in _creem_fetch_transactions(customer_id, api_key, base_url, sandbox):
            subscription_ref = txn.get("subscription")
            subscription_id = (
                subscription_ref.get("id") if isinstance(subscription_ref, dict) else subscription_ref
            )
            if not subscription_id:
                continue
            sub = _creem_fetch_subscription_by_id(str(subscription_id), api_key, base_url, sandbox)
            if sub and sub.get("status") in {"active", "trialing"}:
                return sub, api_key, base_url, sandbox
    return None


def _sync_founding_placeholder_plan(billing_account: BillingAccount | None, sub: dict) -> str:
    """Self-heals a brand-new BillingAccount's safe "founding" placeholder
    (see TenantCreateSerializer -- no live Creem lookup happens at signup
    time) to what the owner actually subscribed to, the first time we
    genuinely see it. Only ever touches "founding" -- a real legacy Founding
    Member with no matching subscription simply won't have one to find here,
    so this can't misfire and overwrite a real plan with a wrong guess.
    Piggybacks on CreemSubscriptionView's existing API call rather than
    making a new one.

    Returns a short reason string for the caller to log/inspect if needed --
    not currently surfaced anywhere; was temporarily exposed as a
    _debug_plan_sync field on CreemSubscriptionView's response while
    root-causing this live (PG-141 test), since logger.info() calls from
    request-handling code weren't showing up in Railway's log capture."""
    if billing_account is None:
        return "no_billing_account"
    if billing_account.plan.key != "founding":
        return f"plan_already_{billing_account.plan.key}"
    if sub.get("status") not in {"active", "trialing"}:
        return f"subscription_status_{sub.get('status')!r}"
    # Per Creem's schema, subscription.product is `oneOf: ProductEntity |
    # string` -- but isn't guaranteed to be populated on every response
    # shape. items[].product_id is the other, always-string source for the
    # same information (already relied on elsewhere for the in-place swap's
    # item_id lookup) -- try both rather than assume one is always there.
    product = sub.get("product")
    product_id = product.get("id") if isinstance(product, dict) else product
    if not product_id:
        items = sub.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            product_id = items[0].get("product_id")
    if not product_id:
        return f"no_product_id_on_subscription:{sub!r}"
    plan = Plan.objects.filter(
        Q(creem_product_id=product_id) | Q(creem_product_id_annual=product_id)
    ).first()
    if plan is None:
        return f"product_id_{product_id!r}_matched_no_plan"
    if plan.key == billing_account.plan.key:
        return f"already_{plan.key}"
    billing_account.plan = plan
    billing_account.save(update_fields=["plan", "updated_at"])
    return f"healed_founding_to_{plan.key}"


class CreemSubscriptionView(_PolarBaseMixin, APIView):
    """PayGlue's own Creem subscription for the logged-in user (Founding
    Member / future Solo-Studio-Agency) -- not the tenant's own connected
    Creem provider (that's GOGU-135, a separate concern)."""

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.authn.creem_access import generate_customer_portal_link

        billing_account = getattr(request.user_profile, "billing_account", None)

        # Three-tier lookup (direct-by-id, customer search, transaction ->
        # subscription-by-id) -- see _creem_subscription_for_switch's
        # docstring. Found live (PG-141 test): the customer search alone can
        # come back completely empty for a real, active subscription.
        found = _creem_subscription_for_switch(request.user_profile)
        if found is not None:
            sub, api_key, _base_url, sandbox = found
            _sync_founding_placeholder_plan(billing_account, sub)
            customer = sub.get("customer")
            customer_id = customer.get("id") if isinstance(customer, dict) else customer
            portal_link = (
                generate_customer_portal_link(customer_id, api_key, sandbox=sandbox) if customer_id else None
            )
            return Response({"subscriptions": [sub], "portal_link": portal_link})

        # Nothing active/trialing found via any tier -- still surface
        # whatever raw (e.g. cancelled) subscriptions the customer search
        # itself returns, for historical display.
        subscriptions: list = []
        portal_link: str | None = None
        for customer_id, api_key, base_url, sandbox in _creem_customer_slots(request.user_profile.email):
            subscriptions += _creem_fetch_subscriptions(customer_id, api_key, base_url, sandbox)
            if portal_link is None:
                portal_link = generate_customer_portal_link(customer_id, api_key, sandbox=sandbox)

        return Response({"subscriptions": subscriptions, "portal_link": portal_link})


class CreemInvoicesView(_PolarBaseMixin, APIView):
    """PayGlue's own Creem invoice/transaction history -- always attempts a
    real list, but a resolvable portal_link is included regardless so the
    frontend has a working fallback if the list itself can't be fetched."""

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.authn.creem_access import generate_customer_portal_link

        invoices: list = []
        portal_link: str | None = None
        for customer_id, api_key, base_url, sandbox in _creem_customer_slots(request.user_profile.email):
            invoices += _creem_fetch_transactions(customer_id, api_key, base_url, sandbox)
            if portal_link is None:
                portal_link = generate_customer_portal_link(customer_id, api_key, sandbox=sandbox)

        invoices.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return Response({"invoices": invoices, "portal_link": portal_link})


class CreemCancelSubscriptionView(_PolarBaseMixin, APIView):
    """Cancels PayGlue's own Creem subscription for the logged-in user,
    scheduled for the end of the current billing period rather than
    immediately -- they keep access through what they've already paid for.
    Write access is owner/billing_admin only via _PolarBaseMixin's
    permission_classes (BillingReadBillingAdminOrOwnerWrite)."""

    def post(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.authn.creem_access import CreemAccessError, cancel_subscription

        # Three-tier lookup (direct-by-id, customer search, transaction ->
        # subscription-by-id) -- see _creem_subscription_for_switch's
        # docstring. Found live (PG-141 test): this view still had its own
        # older two-tier copy of this logic (missing the transaction
        # fallback added to CreemSubscriptionView/the switch endpoint),
        # so it 404'd on exactly the same real subscription those two
        # could already find.
        found = _creem_subscription_for_switch(request.user_profile)
        if found is None:
            return Response({"detail": "No active subscription found."}, status=status.HTTP_404_NOT_FOUND)

        sub, api_key, _base_url, sandbox = found
        subscription_id = sub.get("id")
        if not subscription_id:
            return Response({"detail": "No active subscription found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            result = cancel_subscription(str(subscription_id), api_key, sandbox=sandbox)
        except CreemAccessError as exc:
            # Cloudflare replaces any 502 from the origin with its own
            # generic interstitial regardless of body content (found live
            # debugging PG-150's plan-switch 502) -- 400 is a real
            # client-facing status Cloudflare passes through, so the actual
            # Creem error text reaches the frontend.
            logger.warning("Creem rejected subscription cancel for %s: %s", subscription_id, exc)
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


# Only these hosts may be used as a checkout success_url -- it's attacker
# input in principle (POST body), so an unchecked value would be an open
# redirect via Creem's own hosted checkout page.
_ALLOWED_RETURN_HOSTS = {
    "app.payglue.io",
    "payglue.io",
    "dev.payglue.io",
    "dev2.payglue.io",
    "localhost",
    "127.0.0.1",
}


class CreemCheckoutSessionView(_PolarBaseMixin, APIView):
    """Creates a Creem checkout session for PayGlue's own Solo/Studio/Agency
    plans, initiated from inside the dashboard (PG-150) rather than the
    public landing page. Unlike the landing page's static VITE_CREEM_CHECKOUT_*
    links, this calls Creem's API directly so the success_url can point back
    to the dashboard instead of the public signup page -- no extra Creem
    products needed, since success_url is per-session, not per-product."""

    def post(self, request: Request, tenant_slug: str) -> Response:
        from django.conf import settings

        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        plan_key = request.data.get("plan_key")
        interval = request.data.get("interval", "monthly")
        return_url = request.data.get("return_url")

        if plan_key not in {"solo", "studio", "agency"}:
            return Response({"detail": "Invalid plan_key."}, status=status.HTTP_400_BAD_REQUEST)
        if interval not in {"monthly", "annual"}:
            return Response({"detail": "Invalid interval."}, status=status.HTTP_400_BAD_REQUEST)
        if not return_url or parse.urlparse(return_url).hostname not in _ALLOWED_RETURN_HOSTS:
            return Response({"detail": "Invalid return_url."}, status=status.HTTP_400_BAD_REQUEST)

        plan = Plan.objects.filter(key=plan_key).first()
        if plan is None:
            return Response({"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND)
        product_id = plan.creem_product_id_annual if interval == "annual" else plan.creem_product_id
        if not product_id:
            return Response(
                {"detail": "This plan isn't purchasable yet."}, status=status.HTTP_400_BAD_REQUEST
            )

        api_key = getattr(settings, "CREEM_API_KEY", "")
        if not api_key:
            return Response(
                {"detail": "Checkout isn't configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        from payglue_backend.authn.creem_access import (
            CREEM_API_BASE,
            CreemAccessError,
            _post,
            update_subscription_product,
        )

        billing_account = getattr(request.user_profile, "billing_account", None)

        # Already on a subscription? Switch it in place -- Creem prorates
        # correctly (credits/charges the difference) and there's never a
        # second subscription to accidentally leave running and billing in
        # parallel (found live: a plain new-checkout-per-switch approach did
        # exactly that). Only a genuinely first-ever subscription purchase
        # (no active subscription found at all) falls through to creating a
        # new checkout session below. Uses the direct-or-search fallback
        # (not just the direct ID lookup) since a first-ever purchase never
        # populates creem_subscription_id -- see _creem_subscription_for_switch.
        direct = _creem_subscription_for_switch(request.user_profile)
        if direct is not None:
            existing_sub, existing_api_key, _existing_base_url, existing_sandbox = direct
            existing_sub_id = existing_sub.get("id")
            if existing_sub_id and existing_sub.get("status") in {"active", "trialing"}:
                existing_items = existing_sub.get("items")
                existing_item_id = (
                    existing_items[0].get("id")
                    if isinstance(existing_items, list) and existing_items and isinstance(existing_items[0], dict)
                    else None
                )
                logger.info(
                    "Switching subscription %s to product %s (item_id=%s, sandbox=%s)",
                    existing_sub_id, product_id, existing_item_id, existing_sandbox,
                )
                try:
                    updated = update_subscription_product(
                        str(existing_sub_id),
                        existing_api_key,
                        product_id,
                        sandbox=existing_sandbox,
                        item_id=str(existing_item_id) if existing_item_id else None,
                    )
                    logger.info("Creem update_subscription_product call returned successfully")
                    if billing_account is not None:
                        billing_account.plan = plan
                        update_fields = ["plan", "updated_at"]
                        # Always sync (not just backfill-if-empty) so the next
                        # switch takes the fast, reliable direct-by-ID path
                        # instead of needing this fallback search again --
                        # also self-heals a stale/dead stored ID (e.g. a
                        # subscription cancelled via the Danger Zone) to the
                        # real active one this swap just used.
                        if str(existing_sub_id) != billing_account.creem_subscription_id:
                            billing_account.creem_subscription_id = str(existing_sub_id)
                            update_fields.append("creem_subscription_id")
                        existing_customer = existing_sub.get("customer")
                        existing_customer_id = (
                            existing_customer.get("id")
                            if isinstance(existing_customer, dict)
                            else existing_customer
                        )
                        if existing_customer_id and str(existing_customer_id) != billing_account.creem_customer_id:
                            billing_account.creem_customer_id = str(existing_customer_id)
                            update_fields.append("creem_customer_id")
                        billing_account.save(update_fields=update_fields)
                    response_body = {"updated": True, "subscription": updated}
                except CreemAccessError as exc:
                    # Found live: Django returned a clean 502 here with a
                    # real JSON detail body, but Cloudflare replaces *any*
                    # 502 from the origin with its own generic interstitial
                    # ("invalid or incomplete response") regardless of the
                    # body -- the actual Creem error never reached the
                    # frontend. 400 is a status Cloudflare passes through.
                    logger.warning(
                        "Creem rejected subscription update for %s -> %s: %s", existing_sub_id, product_id, exc
                    )
                    # Creem refuses any in-place item swap while a discount
                    # is active on the subscription, and there's nothing the
                    # customer can do about that from our dashboard -- they
                    # can only cancel or pause, not remove a coupon. Give
                    # them that actionable guidance instead of the raw API
                    # error text.
                    if "discount is active" in str(exc).lower():
                        return Response(
                            {
                                "detail": (
                                    "This subscription has an active discount, which Creem does not allow "
                                    "changing in place. Please cancel your current plan first, then "
                                    "subscribe to the new plan separately."
                                )
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    # Found live: Creem refuses any in-place item swap while
                    # a subscription is still "trialing" (only "active",
                    # i.e. already billing, can be modified) -- there's
                    # nothing the customer can do about that from our
                    # dashboard either, and "cancel and start a new
                    # subscription yourself" is a rough, easy-to-get-wrong
                    # self-serve path for a real customer to be told to do
                    # solo. Point them at support instead.
                    if "must be active" in str(exc).lower():
                        return Response(
                            {
                                "detail": (
                                    "This subscription is still in its trial period, and Creem doesn't allow "
                                    "changing plans until the trial ends and billing begins. If you need to "
                                    "switch sooner, contact us at team@payglue.io or via Support "
                                    f"(https://app.payglue.io/t/{tenant_slug}/support) and we'll sort it out."
                                )
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    return Response(
                        {"detail": f"Could not switch plan: {exc}"}, status=status.HTTP_400_BAD_REQUEST
                    )
                except Exception:
                    # Widened deliberately: found live that a narrower
                    # try/except around only the Creem API call left the
                    # subsequent billing_account.save()/Response(...)
                    # construction unprotected -- whatever crashed there
                    # surfaced as a bare Cloudflare 502 with zero trace on
                    # our end instead of this logged, controlled response.
                    logger.exception(
                        "Unexpected error switching subscription %s to product %s", existing_sub_id, product_id
                    )
                    return Response(
                        {"detail": "Could not switch plan due to an unexpected error."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                return Response(response_body)

        # No existing subscription -- first-ever purchase, needs a real
        # checkout. Tag the current subscription (if any, from the less
        # reliable fallback lookup) so the webhook cancels it once this new
        # one is confirmed, as a safety net -- see PG-150 follow-up.
        previous_subscription_id = _creem_current_subscription_id(request.user_profile)
        metadata: dict[str, str | int | None] = {
            "source": "dashboard_upgrade",
            "billing_account_id": billing_account.id if billing_account else None,
        }
        if previous_subscription_id:
            metadata["previous_subscription_id"] = previous_subscription_id

        try:
            data = _post(
                f"{CREEM_API_BASE}/v1/checkouts",
                api_key,
                {
                    "product_id": product_id,
                    "success_url": return_url,
                    "customer": {"email": request.user_profile.email},
                    "metadata": metadata,
                },
            )
        except CreemAccessError as exc:
            logger.warning("Creem rejected checkout session creation for product %s: %s", product_id, exc)
            return Response(
                {"detail": f"Could not start checkout: {exc}"}, status=status.HTTP_400_BAD_REQUEST
            )

        checkout_url = data.get("checkout_url")
        if not checkout_url:
            return Response({"detail": "Checkout session had no URL."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"checkout_url": checkout_url})


class PolarProductsView(_PolarBaseMixin, APIView):
    """Returns the tenant's own Polar products using their stored access_token."""

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.authn.polar_access import _get, PolarAccessError, POLAR_API_BASE, POLAR_SANDBOX_API_BASE
        from payglue_backend.webhooks.wiring import get_credential_provider
        from payglue_backend.core.models import TenantContext
        from payglue_backend.core.errors import MissingCredentialsError

        try:
            creds = get_credential_provider().get_credentials(
                TenantContext(tenant_slug=tenant_slug), "polar"
            )
        except MissingCredentialsError:
            return Response({"products": [], "has_token": False})

        access_token = creds.get("access_token", "")
        if not access_token:
            return Response({"products": [], "has_token": False})

        def _fetch_products(base_url: str) -> list:
            from payglue_backend.authn.polar_access import _post
            data = _get(f"{base_url}/v1/products?limit=100&is_archived=false", access_token)
            raw_products = [p for p in data.get("items", []) if p.get("id") and p.get("name")]
            products = []
            for p in raw_products:
                prices = p.get("prices") or []
                active_prices = [pr for pr in prices if not pr.get("is_archived")]
                price_id = active_prices[0].get("id") if active_prices else None
                products.append({"id": p.get("id"), "name": p.get("name"), "_price_id": price_id})
            # Fetch existing checkout links, map product_id -> url
            try:
                links_data = _get(f"{base_url}/v1/checkout-links?limit=100", access_token)
                links_by_product: dict = {}
                for link in links_data.get("items", []):
                    pid = link.get("product_id")
                    url = link.get("url")
                    if pid and url and pid not in links_by_product:
                        links_by_product[pid] = url
            except Exception as e:
                logger.warning("polar: failed to fetch checkout-links: %s", e)
                links_by_product = {}
            # For products without a checkout link, create one
            for product in products:
                pid = product["id"]
                if pid in links_by_product:
                    product["checkout_url"] = links_by_product[pid]
                else:
                    try:
                        body = {"product_price_id": product["_price_id"]} if product.get("_price_id") else {"product_id": pid}
                        body["payment_processor"] = "stripe"
                        link = _post(f"{base_url}/v1/checkout-links", access_token, body)
                        product["checkout_url"] = link.get("url")
                    except Exception as e:
                        logger.warning("polar: failed to create checkout link for product %s: %s", pid, e)
                        product["checkout_url"] = None
            for p in products:
                p.pop("_price_id", None)
            return products

        # Try production first; fall back to sandbox (token is environment-specific).
        # TODO: remove sandbox fallback before going live — real customers use production tokens only.
        is_sandbox = False
        try:
            products = _fetch_products(POLAR_API_BASE)
        except PolarAccessError:
            try:
                products = _fetch_products(POLAR_SANDBOX_API_BASE)
                is_sandbox = True
            except PolarAccessError:
                return Response({"products": [], "has_token": True, "error": "Polar API call failed. Check your access token and its scopes (needs products:read)."})

        return Response({"products": products, "has_token": True, "sandbox": is_sandbox})


class LemonSqueezyProductsView(_PolarBaseMixin, APIView):
    """Returns the tenant's Lemon Squeezy variants using their stored api_key."""

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.webhooks.wiring import get_credential_provider
        from payglue_backend.core.errors import MissingCredentialsError
        import urllib.request
        import json as _json

        try:
            creds = get_credential_provider().get_credentials(
                TenantContext(tenant_slug=tenant_slug), "lemonsqueezy"
            )
        except MissingCredentialsError:
            return Response({"products": [], "has_token": False})

        api_key = creds.get("api_key", "")
        if not api_key:
            return Response({"products": [], "has_token": False})

        store_id = creds.get("store_id", "")

        def _ls_get(path: str) -> dict:
            req = urllib.request.Request(
                f"https://api.lemonsqueezy.com{path}",
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/vnd.api+json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return _json.loads(resp.read())

        products_path = "/v1/products?page[size]=100"
        if store_id:
            products_path += f"&filter[store_id]={store_id}"

        try:
            products_data = _ls_get(products_path)
        except Exception as exc:
            logger.warning("lemonsqueezy: failed to fetch products: %s", exc)
            return Response({"products": [], "has_token": True, "error": "Lemon Squeezy API call failed. Check your API key."})

        if not store_id:
            return Response({"products": [], "has_token": True, "needs_store": True})

        product_map: dict[str, dict] = {}
        for item in products_data.get("data", []):
            attrs = item.get("attributes", {})
            if attrs.get("status") != "draft":
                product_map[str(item["id"])] = {
                    "name": attrs.get("name", ""),
                    "buy_now_url": attrs.get("buy_now_url", ""),
                }

        try:
            variants_data = _ls_get("/v1/variants?page[size]=100")
        except Exception as exc:
            logger.warning("lemonsqueezy: failed to fetch variants: %s", exc)
            return Response({"products": [], "has_token": True, "error": "Lemon Squeezy API call failed when fetching variants."})

        products = []
        for item in variants_data.get("data", []):
            attrs = item.get("attributes", {})
            if attrs.get("status") == "draft":
                continue
            variant_id = str(item["id"])
            product_id = str(attrs.get("product_id", ""))
            parent = product_map.get(product_id)
            if parent is None:
                continue
            parent_name = parent.get("name", "")
            variant_name = attrs.get("name", "")
            if variant_name and variant_name.lower() != "default":
                display_name = f"{parent_name} — {variant_name}" if parent_name else variant_name
            else:
                display_name = parent_name or variant_name
            checkout_url = parent.get("buy_now_url", "")
            products.append({"id": variant_id, "name": display_name, "checkout_url": checkout_url})

        products.sort(key=lambda p: p["name"])
        return Response({"products": products, "has_token": True})


class LemonSqueezyStoresView(_PolarBaseMixin, APIView):
    """Returns the list of LS stores for the tenant's api_key so the user can pick the right one."""

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.webhooks.wiring import get_credential_provider
        from payglue_backend.core.errors import MissingCredentialsError
        import urllib.request
        import json as _json

        try:
            creds = get_credential_provider().get_credentials(
                TenantContext(tenant_slug=tenant_slug), "lemonsqueezy"
            )
        except MissingCredentialsError:
            return Response({"stores": [], "has_token": False})

        api_key = creds.get("api_key", "")
        if not api_key:
            return Response({"stores": [], "has_token": False})

        try:
            req = urllib.request.Request(
                "https://api.lemonsqueezy.com/v1/stores",
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/vnd.api+json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
        except Exception as exc:
            logger.warning("lemonsqueezy: failed to fetch stores: %s", exc)
            return Response({"stores": [], "has_token": True, "error": "Lemon Squeezy API call failed. Check your API key."})

        stores = [
            {"id": str(item["id"]), "name": item.get("attributes", {}).get("name", ""), "slug": item.get("attributes", {}).get("slug", "")}
            for item in data.get("data", [])
        ]
        selected_store_id = creds.get("store_id", "")
        return Response({"stores": stores, "has_token": True, "selected_store_id": selected_store_id})


class PayPalProductsView(_PolarBaseMixin, APIView):
    """Returns the tenant's PayPal subscription plans using their stored client_id + client_secret."""

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.webhooks.wiring import get_credential_provider
        from payglue_backend.core.errors import MissingCredentialsError
        import urllib.request
        import urllib.error
        import json as _json
        import base64

        try:
            creds = get_credential_provider().get_credentials(
                TenantContext(tenant_slug=tenant_slug), "paypal"
            )
        except MissingCredentialsError:
            return Response({"products": [], "has_token": False})

        client_id = creds.get("client_id", "")
        client_secret = creds.get("client_secret", "")
        if not client_id or not client_secret:
            return Response({"products": [], "has_token": False})

        sandbox = creds.get("sandbox", "") in ("true", "1", True)
        base_url = "https://api-m.sandbox.paypal.com" if sandbox else "https://api-m.paypal.com"

        credentials_b64 = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        token_req = urllib.request.Request(
            f"{base_url}/v1/oauth2/token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {credentials_b64}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(token_req, timeout=10) as resp:
                token_data = _json.loads(resp.read())
        except Exception as exc:
            logger.warning("paypal: OAuth token failed: %s", exc)
            return Response({"products": [], "has_token": True, "error": "PayPal OAuth failed. Check your Client ID and Secret."})

        access_token = token_data.get("access_token")
        if not access_token:
            return Response({"products": [], "has_token": True, "error": "PayPal OAuth returned no access token."})

        plans_req = urllib.request.Request(
            f"{base_url}/v1/billing/plans?page_size=20&status=ACTIVE",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(plans_req, timeout=10) as resp:
                plans_data = _json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            logger.warning("paypal: plans fetch failed: HTTP %s", exc.code)
            return Response({"products": [], "has_token": True, "error": f"PayPal API error: HTTP {exc.code}"})
        except Exception as exc:
            logger.warning("paypal: plans fetch failed: %s", exc)
            return Response({"products": [], "has_token": True, "error": "PayPal API call failed."})

        products = []
        for plan in plans_data.get("plans", []):
            plan_id = plan.get("id", "")
            name = plan.get("name", plan_id)
            products.append({"id": plan_id, "name": name, "checkout_url": ""})

        products.sort(key=lambda p: p["name"])
        return Response({"products": products, "has_token": True})


class GumroadProductsView(_PolarBaseMixin, APIView):
    """Returns the tenant's Gumroad products using their stored access_token."""

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.webhooks.wiring import get_credential_provider
        from payglue_backend.core.errors import MissingCredentialsError
        import urllib.request
        import urllib.error
        import json as _json
        from urllib.parse import quote

        try:
            creds = get_credential_provider().get_credentials(
                TenantContext(tenant_slug=tenant_slug), "gumroad"
            )
        except MissingCredentialsError:
            return Response({"products": [], "has_token": False})

        access_token = creds.get("access_token", "")
        if not access_token:
            return Response({"products": [], "has_token": False})

        req = urllib.request.Request(
            f"https://api.gumroad.com/v2/products?access_token={quote(access_token)}",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            logger.warning("gumroad: products fetch failed: HTTP %s", exc.code)
            return Response({"products": [], "has_token": True, "error": f"Gumroad API error: HTTP {exc.code}"})
        except Exception as exc:
            logger.warning("gumroad: products fetch failed: %s", exc)
            return Response({"products": [], "has_token": True, "error": "Gumroad API call failed. Check your access token."})

        if not data.get("success"):
            return Response({"products": [], "has_token": True, "error": "Gumroad API call failed. Check your access token."})

        products = [
            {
                "id": str(item.get("id", "")),
                "name": item.get("name", ""),
                "checkout_url": item.get("short_url", ""),
            }
            for item in data.get("products", [])
        ]
        products.sort(key=lambda p: p["name"])
        return Response({"products": products, "has_token": True})


class PaddleProductsView(_PolarBaseMixin, APIView):
    """Returns the tenant's Paddle products using their stored api_key."""

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.webhooks.wiring import get_credential_provider
        from payglue_backend.core.errors import MissingCredentialsError
        import urllib.request
        import urllib.error
        import json as _json

        try:
            creds = get_credential_provider().get_credentials(
                TenantContext(tenant_slug=tenant_slug), "paddle"
            )
        except MissingCredentialsError:
            return Response({"products": [], "has_token": False})

        api_key = creds.get("api_key", "")
        if not api_key:
            return Response({"products": [], "has_token": False})

        sandbox = creds.get("sandbox", "") in ("true", "1", True)
        base_url = "https://sandbox-api.paddle.com" if sandbox else "https://api.paddle.com"

        req = urllib.request.Request(
            f"{base_url}/products?status=active&per_page=100",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            logger.warning("paddle: products fetch failed: HTTP %s", exc.code)
            return Response({"products": [], "has_token": True, "error": f"Paddle API error: HTTP {exc.code}"})
        except Exception as exc:
            logger.warning("paddle: products fetch failed: %s", exc)
            return Response({"products": [], "has_token": True, "error": "Paddle API call failed. Check your API key."})

        products = [
            {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                # Paddle Billing has no static per-product checkout link --
                # checkout is driven client-side (Paddle.js overlay) from a
                # price id. Same manual-entry pattern as PayPal.
                "checkout_url": "",
            }
            for item in data.get("data", [])
        ]
        products.sort(key=lambda p: p["name"])
        return Response({"products": products, "has_token": True})


class CreemProductsView(_PolarBaseMixin, APIView):
    """Returns the tenant's Creem products using their stored api_key."""

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.webhooks.wiring import get_credential_provider
        from payglue_backend.core.errors import MissingCredentialsError
        from payglue_backend.webhooks.adapters.creem import _read_error_body, creem_get_any_mode
        import urllib.error

        try:
            creds = get_credential_provider().get_credentials(
                TenantContext(tenant_slug=tenant_slug), "creem"
            )
        except MissingCredentialsError:
            return Response({"products": [], "has_token": False})

        api_key = creds.get("api_key", "")
        if not api_key:
            return Response({"products": [], "has_token": False})

        try:
            data = creem_get_any_mode("/v1/products/search", api_key)
        except urllib.error.HTTPError as exc:
            detail = _read_error_body(exc)
            logger.warning("creem: products fetch failed: HTTP %s %s", exc.code, detail)
            error_message = f"Creem API error: HTTP {exc.code}."
            if detail:
                error_message += f" {detail}"
            return Response({"products": [], "has_token": True, "error": error_message})
        except Exception as exc:
            logger.warning("creem: products fetch failed: %s", exc)
            return Response({"products": [], "has_token": True, "error": "Creem API call failed. Check your API key."})

        # Verified against docs.creem.io/api-reference/endpoint/search-products
        # (PG-143): response is {"items": [...], "pagination": {...}}, each
        # item has a static "product_url" checkout link -- no per-session
        # checkout creation needed, unlike Paddle/PayPal.
        items = data if isinstance(data, list) else (data.get("items") or data.get("data") or [])
        products = [
            {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "checkout_url": item.get("product_url", ""),
            }
            for item in items
            if isinstance(item, dict)
        ]
        products.sort(key=lambda p: p["name"])
        return Response({"products": products, "has_token": True})


class PatreonProductsView(_PolarBaseMixin, APIView):
    """PG-123: returns the tenant's Patreon tiers (as "products" for the
    shared mapping picker) using their stored Creator's Access Token.

    Patreon has no per-tier checkout link -- patrons join via the campaign
    page, not a product URL -- so checkout_url is always empty, same as
    Paddle/PayPal.
    """

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            self._require_tenant_context(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        from payglue_backend.webhooks.wiring import get_credential_provider
        from payglue_backend.core.errors import MissingCredentialsError
        import urllib.request
        import urllib.error
        import json as _json

        try:
            creds = get_credential_provider().get_credentials(
                TenantContext(tenant_slug=tenant_slug), "patreon"
            )
        except MissingCredentialsError:
            return Response({"products": [], "has_token": False})

        access_token = creds.get("access_token", "")
        if not access_token:
            return Response({"products": [], "has_token": False})

        # One call returns the creator's campaign(s) with their tiers embedded
        # in JSON:API `included`. amount_cents lets us label a tier with its
        # price so mappings are easy to tell apart.
        req = urllib.request.Request(
            "https://www.patreon.com/api/oauth2/v2/campaigns"
            "?include=tiers&fields%5Btier%5D=title,amount_cents",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            logger.warning("patreon: tiers fetch failed: HTTP %s", exc.code)
            return Response({"products": [], "has_token": True, "error": f"Patreon API error: HTTP {exc.code}"})
        except Exception as exc:
            logger.warning("patreon: tiers fetch failed: %s", exc)
            return Response({"products": [], "has_token": True, "error": "Patreon API call failed. Check your access token."})

        included = data.get("included") if isinstance(data, dict) else None
        products = []
        for item in included or []:
            if not isinstance(item, dict) or item.get("type") != "tier":
                continue
            attrs = item.get("attributes") or {}
            title = attrs.get("title") or "Untitled tier"
            amount_cents = attrs.get("amount_cents")
            name = title
            if isinstance(amount_cents, int):
                name = f"{title} (${amount_cents / 100:.2f})"
            products.append({"id": str(item.get("id", "")), "name": name, "checkout_url": ""})
        products.sort(key=lambda p: p["name"])
        return Response({"products": products, "has_token": True})


class SupportRequestView(APIView):
    """Open a support request, and list the ones this publication has open.

    Any member can write in, because "I cannot do X" is exactly the sort of
    thing that comes from somebody who is not the owner.
    """

    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [HasUserProfile]

    MAX_MESSAGE = 5000

    def _tenant(self, request: Request, tenant_slug: str) -> Tenant:
        tenant_ctx = getattr(request, "tenant_ctx", None)
        if (
            not isinstance(tenant_ctx, TenantContext)
            or tenant_ctx.tenant_slug != tenant_slug
        ):
            raise Tenant.DoesNotExist
        return Tenant.objects.get(id=tenant_ctx.tenant_id, slug=tenant_slug)

    def get(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._tenant(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        requests = list(tenant.support_requests.all()[:20])
        support.sync_statuses(requests)
        return Response({"requests": SupportRequestSerializer(requests, many=True).data})

    def post(self, request: Request, tenant_slug: str) -> Response:
        try:
            tenant = self._tenant(request, tenant_slug)
        except Tenant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        message = str(request.data.get("message") or "").strip()
        if not message:
            return Response(
                {"detail": "A message is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = getattr(request, "user_profile", None)
        # The signed-in address wins over anything posted, so a request cannot
        # be filed under somebody else's email.
        email = getattr(profile, "email", "") or str(request.data.get("email") or "")
        if not email:
            return Response(
                {"detail": "No email address on file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        topic = str(request.data.get("topic") or "")
        if topic not in support.TOPIC_LABELS:
            topic = ""

        support_request = support.create_support_request(
            tenant=tenant,
            email=email,
            name=str(request.data.get("name") or "")[:200],
            topic=topic,
            message=message[: self.MAX_MESSAGE],
        )
        return Response(
            {"request": SupportRequestSerializer(support_request).data},
            status=status.HTTP_201_CREATED,
        )

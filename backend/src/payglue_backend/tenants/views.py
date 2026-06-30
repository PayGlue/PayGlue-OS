# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import logging
import re

from django.db import IntegrityError

logger = logging.getLogger(__name__)
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import SAFE_METHODS
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from payglue_backend.authn.authentication import FirebaseBearerAuthentication
from payglue_backend.authn.rbac import resolve_tenant_membership
from payglue_backend.core.models import TenantContext
from payglue_backend.tenants.audit import write_public_audit_event
from payglue_backend.tenants.models import (
    BillingProfile,
    PublicAuditEvent,
    Tenant,
    TenantMembership,
    UserProfile,
)
from payglue_backend.tenants.serializers import (
    BillingProfileSerializer,
    TenantCreateSerializer,
    TenantMembershipSummarySerializer,
    TeamMemberCreateSerializer,
    TeamMemberRoleUpdateSerializer,
    TeamMembershipSerializer,
)


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

        if (
            actor_membership.role == TenantMembership.Role.ADMIN
            and requested_role == TenantMembership.Role.OWNER
        ):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

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
            user_profile = UserProfile.objects.filter(email=str(email)).first()
            if user_profile is None:
                return Response(
                    {"detail": "User profile for email was not found."},
                    status=status.HTTP_400_BAD_REQUEST,
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
        return Response(
            TeamMembershipSerializer(membership).data, status=status.HTTP_201_CREATED
        )


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
            membership.delete()
        write_public_audit_event(
            tenant=tenant,
            actor_membership=actor_membership,
            event_type=PublicAuditEvent.EventType.TEAM_MEMBER_REMOVED,
            target_type="membership",
            target_id=removed_id,
            metadata={},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class BillingProfileView(APIView):
    authentication_classes = [FirebaseBearerAuthentication]
    permission_classes = [BillingReadBillingAdminOrOwnerWrite]

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

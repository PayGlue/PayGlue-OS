# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from collections.abc import Collection

from django.http import HttpRequest
from rest_framework.permissions import SAFE_METHODS, BasePermission

from payglue_backend.core.models import TenantContext
from payglue_backend.tenants.models import Tenant, TenantMembership


def resolve_tenant_membership(request: HttpRequest) -> TenantMembership | None:
    user_profile = getattr(request, "user_profile", None)
    tenant_ctx = getattr(request, "tenant_ctx", None)
    if user_profile is None or not isinstance(tenant_ctx, TenantContext):
        return None

    queryset = TenantMembership.objects.filter(
        user_profile=user_profile,
        tenant__status=Tenant.Status.ACTIVE,
    )
    if tenant_ctx.tenant_id is not None:
        return queryset.filter(tenant_id=tenant_ctx.tenant_id).first()
    return queryset.filter(tenant__slug=tenant_ctx.tenant_slug).first()


def _membership_role(role_or_membership: str | TenantMembership | None) -> str | None:
    if role_or_membership is None:
        return None
    if isinstance(role_or_membership, TenantMembership):
        return role_or_membership.role
    return role_or_membership


def has_tenant_role(
    role_or_membership: str | TenantMembership | None,
    allowed_roles: Collection[str],
) -> bool:
    return _membership_role(role_or_membership) in allowed_roles


def is_write_denied_for_readonly(
    role_or_membership: str | TenantMembership | None,
) -> bool:
    return (
        _membership_role(role_or_membership) == TenantMembership.Role.SUPPORT_READONLY
    )


class HasTenantMembership(BasePermission):
    def has_permission(self, request: HttpRequest, view: object) -> bool:
        del view
        return resolve_tenant_membership(request) is not None


class DenyReadonlyWrites(BasePermission):
    def has_permission(self, request: HttpRequest, view: object) -> bool:
        del view
        membership = resolve_tenant_membership(request)
        if membership is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        return not is_write_denied_for_readonly(membership)


class TenantReadOwnerAdminWrite(BasePermission):
    def has_permission(self, request: HttpRequest, view: object) -> bool:
        del view
        membership = resolve_tenant_membership(request)
        if membership is None:
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_tenant_role(
            membership,
            {"owner", "admin"},
        )

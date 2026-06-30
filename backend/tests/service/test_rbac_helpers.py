import pytest
from django.test import RequestFactory

from payglue_backend.authn.rbac import (
    DenyReadonlyWrites,
    has_tenant_role,
    is_write_denied_for_readonly,
    resolve_tenant_membership,
)
from payglue_backend.core.models import TenantContext
from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile


pytestmark = pytest.mark.django_db


def test_resolve_tenant_membership_from_request_context() -> None:
    tenant = Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")
    profile = UserProfile.objects.create(firebase_uid="uid_1", email="u1@example.com")
    membership = TenantMembership.objects.create(
        tenant=tenant,
        user_profile=profile,
        role=TenantMembership.Role.ADMIN,
    )
    request = RequestFactory().get("/t/tenant-a/api/v1/example")
    request.user_profile = profile
    request.tenant_ctx = TenantContext(tenant_id=tenant.id, tenant_slug=tenant.slug)

    resolved = resolve_tenant_membership(request)

    assert resolved is not None
    assert resolved.id == membership.id


@pytest.mark.parametrize(
    ("role", "can_manage", "write_denied"),
    [
        (TenantMembership.Role.OWNER, True, False),
        (TenantMembership.Role.ADMIN, True, False),
        (TenantMembership.Role.BILLING_ADMIN, True, False),
        (TenantMembership.Role.SUPPORT_READONLY, False, True),
    ],
)
def test_rbac_role_matrix(role: str, can_manage: bool, write_denied: bool) -> None:
    assert (
        has_tenant_role(
            role,
            {
                TenantMembership.Role.OWNER,
                TenantMembership.Role.ADMIN,
                TenantMembership.Role.BILLING_ADMIN,
            },
        )
        is can_manage
    )
    assert is_write_denied_for_readonly(role) is write_denied


def test_resolve_tenant_membership_ignores_inactive_tenant_membership() -> None:
    tenant = Tenant.objects.create(
        slug="tenant-inactive",
        schema_name="tenant_inactive",
        status=Tenant.Status.DISABLED,
    )
    profile = UserProfile.objects.create(firebase_uid="uid_2", email="u2@example.com")
    TenantMembership.objects.create(
        tenant=tenant,
        user_profile=profile,
        role=TenantMembership.Role.ADMIN,
    )
    request = RequestFactory().get("/t/tenant-inactive/api/v1/example")
    request.user_profile = profile
    request.tenant_ctx = TenantContext(tenant_id=tenant.id, tenant_slug=tenant.slug)

    resolved = resolve_tenant_membership(request)

    assert resolved is None


def test_deny_readonly_writes_denies_safe_methods_without_membership() -> None:
    request = RequestFactory().get("/t/tenant-a/api/v1/example")
    request.user_profile = None
    request.tenant_ctx = None

    allowed = DenyReadonlyWrites().has_permission(request, object())

    assert allowed is False

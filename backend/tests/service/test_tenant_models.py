import pytest
from django_tenants.models import DomainMixin, TenantMixin
from django.core.exceptions import ValidationError

from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile


pytestmark = pytest.mark.django_db


def test_tenant_slug_is_immutable() -> None:
    tenant = Tenant.objects.create(slug="acme", schema_name="acme")
    tenant.slug = "renamed"

    with pytest.raises(ValidationError):
        tenant.full_clean()


def test_tenant_membership_role_choices_include_support_readonly() -> None:
    profile = UserProfile.objects.create(firebase_uid="uid_1", email="u@example.com")
    tenant = Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")

    membership = TenantMembership.objects.create(
        tenant=tenant,
        user_profile=profile,
        role=TenantMembership.Role.SUPPORT_READONLY,
    )

    assert membership.role == "support_readonly"


def test_tenant_slug_rejects_uppercase_and_underscore() -> None:
    tenant = Tenant(slug="Bad_Slug", schema_name="bad_slug")

    with pytest.raises(ValidationError):
        tenant.full_clean()


def test_tenant_model_is_django_tenants_compatible() -> None:
    assert issubclass(Tenant, TenantMixin)


def test_tenant_domain_model_is_django_tenants_compatible() -> None:
    from payglue_backend.tenants.models import TenantDomain

    assert issubclass(TenantDomain, DomainMixin)

import pytest
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


def test_tenant_domain_keeps_the_columns_the_mixin_used_to_provide() -> None:
    """PG-273 declared domain, tenant and is_primary locally instead of
    inheriting django_tenants' DomainMixin. The table must not move: this asserts
    the shape rather than the ancestry, which is what the two tests it replaces
    were reaching for."""
    from payglue_backend.tenants.models import TenantDomain

    fields = {f.name: f for f in TenantDomain._meta.get_fields()}

    assert fields["domain"].max_length == 253
    assert fields["domain"].unique is True
    assert fields["is_primary"].default is True
    assert fields["tenant"].remote_field.related_name == "domains"

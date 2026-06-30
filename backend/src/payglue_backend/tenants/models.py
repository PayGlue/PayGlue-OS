# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Tenant(TenantMixin):
    class Status(models.TextChoices):
        ACTIVE = "active", "active"
        SUSPENDED = "suspended", "suspended"
        DISABLED = "disabled", "disabled"

    slug = models.SlugField(
        max_length=64,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
                message="Slug must use lowercase letters, numbers, and hyphens.",
            )
        ],
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self) -> None:
        super().clean()

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class UserProfile(models.Model):
    firebase_uid = models.CharField(max_length=255, unique=True)
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False


class InvitationGrant(models.Model):
    class Source(models.TextChoices):
        PREFINERY = "prefinery", "Prefinery"
        POLAR_CHECKOUT = "polar_checkout", "Polar Checkout"
        POLAR_LICENSE = "polar_license", "Polar License Key"
        MANUAL = "manual", "Manual"

    email = models.EmailField(unique=True)
    invitation_code_prefix = models.CharField(max_length=16, blank=True, default="")
    source = models.CharField(
        max_length=32, choices=Source.choices, default=Source.PREFINERY
    )
    verified_at = models.DateTimeField(auto_now=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AccessRedemption(models.Model):
    """Tracks Polar checkout IDs and license keys that have already been used to
    create an InvitationGrant, preventing double-redemption."""

    class Kind(models.TextChoices):
        CHECKOUT = "checkout", "Checkout"
        LICENSE_KEY = "license_key", "License Key"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    redemption_id = models.CharField(max_length=256, unique=True)
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["redemption_id"])]


class TenantMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "owner"
        ADMIN = "admin", "admin"
        BILLING_ADMIN = "billing_admin", "billing_admin"
        SUPPORT_READONLY = "support_readonly", "support_readonly"

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="memberships"
    )
    user_profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="tenant_memberships",
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user_profile"],
                name="unique_tenant_user_membership",
            )
        ]


class BillingProfile(models.Model):
    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name="billing_profile",
    )
    legal_name = models.CharField(max_length=255, blank=True, default="")
    billing_email = models.EmailField(blank=True, default="")
    country_code = models.CharField(max_length=2, blank=True, default="")
    tax_id = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PublicAuditEvent(models.Model):
    class EventType(models.TextChoices):
        TEAM_MEMBER_CREATED = "team.member_created", "team.member_created"
        TEAM_MEMBER_ROLE_UPDATED = (
            "team.member_role_updated",
            "team.member_role_updated",
        )
        TEAM_MEMBER_REMOVED = "team.member_removed", "team.member_removed"
        BILLING_PROFILE_UPDATED = "billing.profile_updated", "billing.profile_updated"
        INTEGRATION_CREDENTIALS_WRITTEN = (
            "integration.credentials_written",
            "integration.credentials_written",
        )
        EVENT_REPLAY_REQUESTED = "event.replay_requested", "event.replay_requested"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="public_audit_events",
    )
    actor_membership = models.ForeignKey(
        TenantMembership,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emitted_audit_events",
    )
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=128, blank=True, default="")
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "event_type", "created_at"]),
        ]


class TenantDomain(DomainMixin):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

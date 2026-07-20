# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from payglue_backend.authn.lifecycle_emails import send_lifecycle_email
from payglue_backend.tenants.models import (
    BillingAccount,
    BillingProfile,
    InvitationGrant,
    Plan,
    PublicAuditEvent,
    FoundingSale,
    ServicePin,
    SupportRequest,
    Tenant,
    TenantMembership,
    UserProfile,
    LifecycleEmailTemplate,
)


class TenantMembershipSummarySerializer(serializers.Serializer):
    tenant_slug = serializers.CharField(source="tenant.slug")
    role = serializers.CharField()


class TenantCreateSerializer(serializers.Serializer):
    slug = serializers.SlugField(max_length=64)

    def validate_slug(self, value: str) -> str:
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Tenant slug already exists.")

        tenant = Tenant(slug=value, schema_name=value.replace("-", "_"))
        try:
            tenant.full_clean()
        except DjangoValidationError as exc:
            if isinstance(exc.message_dict, dict) and "slug" in exc.message_dict:
                raise serializers.ValidationError(exc.message_dict["slug"]) from exc
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def create(self, validated_data: dict[str, object]) -> TenantMembership:
        user_profile = self.context["user_profile"]
        if not isinstance(user_profile, UserProfile):
            raise serializers.ValidationError("Authenticated user profile is required.")

        slug = str(validated_data["slug"])
        with transaction.atomic():
            # Found live (PG-141 test): nothing in the codebase ever created a
            # BillingAccount for a new signup -- only the one-time migration
            # backfill (0012) touched pre-existing tenants. Every tenant
            # created since Plan/BillingAccount shipped (PG-138/PR#91) has
            # had billing_account=None, silently exempting it from all plan
            # enforcement and leaving the dashboard's plan name/usage cards
            # with nothing to read. Default to "founding" (unlimited) here --
            # safe or unknown purchases, never blocks anyone -- the actual
            # purchased plan gets synced correctly the moment the owner
            # touches anything plan-related (e.g. a dashboard plan switch,
            # which already sets billing_account.plan from the real Creem
            # subscription).
            # PG-183: if this user signed up by redeeming a PayGlue license code,
            # provision their first BillingAccount as a "Tester" on the code's plan
            # with the code's access window, instead of the default founding plan.
            # The window (if any) starts now; expire_tester_access later flips it
            # into the standard 30-day cancellation grace.
            tester_grant = (
                InvitationGrant.objects.filter(
                    email__iexact=user_profile.email, license_code__isnull=False
                )
                .select_related("license_code", "license_code__plan")
                .first()
            )
            if tester_grant is not None:
                code = tester_grant.license_code
                expires_at = (
                    timezone.now() + timedelta(days=code.access_days)
                    if code.access_days
                    else None
                )
                billing_defaults = {
                    "plan": code.plan,
                    "is_tester": True,
                    "tester_access_expires_at": expires_at,
                    "license_code": code,
                }
            else:
                billing_defaults = {"plan": Plan.objects.get(key="founding")}

            # PG-210: if this email bought a founding spot, stamp which batch
            # and what it locked. Done here because this is the moment the
            # purchase email and the account first meet -- matching them up by
            # email months later turns into handwork the first time somebody
            # checked out with a different address than they signed up with.
            # The rate is copied from the sale, not derived from the ladder, so
            # a later price change cannot move what they were promised.
            founding_sale = (
                FoundingSale.objects.filter(
                    email__iexact=user_profile.email, tier__isnull=False
                )
                .order_by("created_at")
                .first()
            )
            if founding_sale is not None:
                billing_defaults["founding_tier"] = founding_sale.tier
                billing_defaults["founding_price_cents"] = founding_sale.price_cents
            billing_account, billing_created = BillingAccount.objects.get_or_create(
                owner=user_profile,
                defaults=billing_defaults,
            )
            if billing_created:
                # on_commit, not inline: this runs inside the atomic block that
                # also creates the tenant and membership. A welcome email sent
                # before that commits could describe an account a rollback then
                # undid, and the send itself must never be what fails signup.
                transaction.on_commit(
                    lambda: send_lifecycle_email(
                        billing_account, LifecycleEmailTemplate.Trigger.ONBOARDING_WELCOME
                    )
                )
            tenant = Tenant.objects.create(
                slug=slug, schema_name=slug.replace("-", "_"), billing_account=billing_account
            )
            membership = TenantMembership.objects.create(
                tenant=tenant,
                user_profile=user_profile,
                role=TenantMembership.Role.OWNER,
            )
        return membership


class TeamMembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user_profile.email", read_only=True)
    firebase_uid = serializers.CharField(
        source="user_profile.firebase_uid", read_only=True
    )

    class Meta:
        model = TenantMembership
        fields = ["id", "email", "firebase_uid", "role", "created_at", "updated_at"]
        read_only_fields = fields


class TeamMemberCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    firebase_uid = serializers.CharField(required=False, max_length=255)
    role = serializers.ChoiceField(choices=TenantMembership.Role.choices)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        email = attrs.get("email")
        firebase_uid = attrs.get("firebase_uid")
        if not email and not firebase_uid:
            raise serializers.ValidationError(
                "One of email or firebase_uid is required."
            )
        return attrs


class TeamMemberRoleUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=TenantMembership.Role.choices)


class BillingProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillingProfile
        fields = ["legal_name", "billing_email", "country_code", "tax_id"]


class ServicePinSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePin
        fields = ["code", "created_at", "expires_at", "revoked_at"]
        read_only_fields = fields


class SupportRequestSerializer(serializers.ModelSerializer):
    """What the customer is allowed to see about their own request.

    Note what is absent: the Linear issue id, and any issue content. Internal
    comments live on that issue, so exposing it is exactly the mistake this
    design exists to avoid. Reference plus status is the whole contract.
    """

    reference = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SupportRequest
        fields = ["id", "reference", "topic", "status", "status_label", "created_at"]
        read_only_fields = fields


class PublicAuditEventSerializer(serializers.ModelSerializer):
    actor_membership_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = PublicAuditEvent
        fields = [
            "id",
            "event_type",
            "target_type",
            "target_id",
            "metadata",
            "actor_membership_id",
            "created_at",
        ]
        read_only_fields = fields

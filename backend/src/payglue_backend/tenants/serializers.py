# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from payglue_backend.tenants.models import (
    BillingProfile,
    PublicAuditEvent,
    Tenant,
    TenantMembership,
    UserProfile,
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
            tenant = Tenant.objects.create(
                slug=slug, schema_name=slug.replace("-", "_")
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

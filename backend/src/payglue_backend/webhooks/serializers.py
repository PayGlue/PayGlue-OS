# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from rest_framework import serializers

from payglue_backend.webhooks.models import (
    IntegrationConfig,
    ProductMapping,
    WebhookInboundEvent,
)


class IntegrationConfigSerializer(serializers.ModelSerializer):
    def validate_provider_type(self, value: str) -> str:
        provider_key = self.context.get("provider_key")
        allowed_map = self.context.get("allowed_provider_types", {})
        allowed = (
            allowed_map.get(provider_key, set())
            if isinstance(allowed_map, dict)
            else set()
        )
        if value not in allowed:
            raise serializers.ValidationError(
                f"Unsupported provider_type '{value}' for provider_key '{provider_key}'."
            )
        return value

    class Meta:
        model = IntegrationConfig
        fields = ["provider_key", "enabled", "provider_type", "metadata"]
        read_only_fields = ["provider_key"]


class ProductMappingSerializer(serializers.ModelSerializer):
    def validate_payment_provider(self, value: str) -> str:
        allowed = self.context.get("allowed_payment_providers")
        if isinstance(allowed, set) and value not in allowed:
            raise serializers.ValidationError("Unsupported payment provider.")
        return value

    def validate_action(self, value: str) -> str:
        allowed = {choice for choice, _ in ProductMapping.Action.choices}
        if value not in allowed:
            raise serializers.ValidationError("Unsupported action.")
        return value

    class Meta:
        model = ProductMapping
        fields = [
            "id",
            "payment_provider",
            "event_type",
            "external_product_id",
            "entitlement_key",
            "action",
            "quantity",
            "is_active",
            "metadata",
        ]
        read_only_fields = ["id"]


class IntegrationCredentialsSerializer(serializers.Serializer):
    credentials = serializers.DictField(
        child=serializers.CharField(allow_blank=False),
        allow_empty=False,
    )

    def validate_credentials(self, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise serializers.ValidationError("Credential keys must be non-empty.")
            if not isinstance(item, str) or not item:
                raise serializers.ValidationError(
                    "Credential values must be non-empty."
                )
            normalized[key] = item
        return normalized


class WebhookInboundEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookInboundEvent
        fields = [
            "id",
            "tenant_slug",
            "provider",
            "status",
            "attempts",
            "max_attempts",
            "next_attempt_at",
            "last_error",
            "payload_snapshot",
            "headers_snapshot",
            "endpoint_path",
            "endpoint_metadata",
            "created_at",
            "processing_started_at",
            "processed_at",
            "failed_at",
            "dead_lettered_at",
            "updated_at",
        ]

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
class PayGlueError(Exception):
    """Base domain error for the webhook core."""


class AdapterNotRegisteredError(PayGlueError):
    def __init__(self, adapter_type: str, key: str) -> None:
        super().__init__(f"No {adapter_type} adapter is registered for key '{key}'")
        self.adapter_type = adapter_type
        self.key = key


class AdapterAlreadyRegisteredError(PayGlueError):
    def __init__(self, adapter_type: str, key: str) -> None:
        super().__init__(f"{adapter_type} adapter key '{key}' is already registered")
        self.adapter_type = adapter_type
        self.key = key


class InvalidWebhookSignatureError(PayGlueError):
    """Webhook signature is invalid."""


class UnsupportedEventTypeError(PayGlueError):
    """Webhook event type is not supported by adapter."""


class MissingCustomerIdentityError(PayGlueError):
    """Webhook event is missing customer identity fields."""


class InvalidIdempotencyKeyError(PayGlueError):
    """Idempotency key format is invalid."""


class MissingCredentialsError(PayGlueError):
    def __init__(
        self,
        tenant_slug: str,
        provider_key: str,
        missing_fields: tuple[str, ...],
    ) -> None:
        joined = ", ".join(missing_fields)
        super().__init__(
            f"Missing credentials for tenant '{tenant_slug}' provider '{provider_key}': {joined}"
        )
        self.tenant_slug = tenant_slug
        self.provider_key = provider_key
        self.missing_fields = missing_fields


class InvalidWebhookPayloadError(PayGlueError):
    """Webhook payload does not match expected schema."""


class CmsApplyEntitlementError(PayGlueError):
    """CMS entitlement call failed."""

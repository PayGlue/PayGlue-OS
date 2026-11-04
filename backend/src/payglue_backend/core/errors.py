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


class AccessRunsUntilError(UnsupportedEventTypeError):
    """A cancellation that takes effect only when the paid period ends.

    Skipped like any other event that changes nothing now. A provider that
    sends nothing when the period ends hands over `end_payload`, a delivery
    of its own that ends access, and the worker queues it for `ends_at`.
    """

    def __init__(self, message: str, ends_at, end_payload: bytes | None = None) -> None:
        super().__init__(message)
        self.ends_at = ends_at
        self.end_payload = end_payload


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


class PlanLimitExceededError(PayGlueError):
    def __init__(self, resource: str, limit: int) -> None:
        super().__init__(
            f"Your plan allows up to {limit} {resource}. Upgrade to add more."
        )
        self.resource = resource
        self.limit = limit

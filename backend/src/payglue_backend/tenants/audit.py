# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from collections.abc import Mapping

from payglue_backend.tenants.models import PublicAuditEvent, Tenant, TenantMembership

_SENSITIVE_METADATA_KEYS = {
    "secret",
    "password",
    "token",
    "credential",
    "private_key",
    "api_key",
}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_METADATA_KEYS)


def sanitize_audit_metadata(value: object) -> object:
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            key_str = str(key)
            if _is_sensitive_key(key_str):
                sanitized[key_str] = "[redacted]"
            else:
                sanitized[key_str] = sanitize_audit_metadata(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_audit_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_audit_metadata(item) for item in value]
    return value


def write_public_audit_event(
    *,
    tenant: Tenant,
    actor_membership: TenantMembership | None,
    event_type: str,
    target_type: str = "",
    target_id: str = "",
    metadata: Mapping[str, object] | None = None,
) -> PublicAuditEvent:
    sanitized_metadata = sanitize_audit_metadata(dict(metadata or {}))
    if not isinstance(sanitized_metadata, dict):
        sanitized_metadata = {}
    return PublicAuditEvent.objects.create(
        tenant=tenant,
        actor_membership=actor_membership,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        metadata=sanitized_metadata,
    )

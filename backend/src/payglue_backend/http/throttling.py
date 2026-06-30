# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
from django.core.exceptions import ImproperlyConfigured
from rest_framework.settings import api_settings
from rest_framework.throttling import ScopedRateThrottle


class DynamicScopedRateThrottle(ScopedRateThrottle):
    def get_rate(self) -> str | None:
        if not self.scope:
            raise ImproperlyConfigured(
                "DynamicScopedRateThrottle requires throttle_scope to be set."
            )
        rates = api_settings.DEFAULT_THROTTLE_RATES
        rate = rates.get(self.scope)
        if not rate:
            raise ImproperlyConfigured(
                f"Throttle rate for scope '{self.scope}' is not configured."
            )
        return rate

    def get_cache_key(self, request, view):
        base_key = super().get_cache_key(request, view)
        if base_key is None:
            return None

        kwargs = getattr(view, "kwargs", {})
        tenant_slug = kwargs.get("tenant_slug") if isinstance(kwargs, dict) else None
        if isinstance(tenant_slug, str) and tenant_slug:
            return f"{base_key}:{tenant_slug}"

        return base_key

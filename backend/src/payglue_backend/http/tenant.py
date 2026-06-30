# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import re
from collections.abc import Callable

from django.conf import settings
from django.db import connection
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound

from payglue_backend.core.models import TenantContext
from payglue_backend.tenants.models import Tenant

_TENANT_PATH_PATTERN = re.compile(
    r"^/t/(?P<tenant_slug>[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:/|$)"
)


def extract_tenant_slug(path: str) -> str | None:
    match = _TENANT_PATH_PATTERN.match(path)
    if match is None:
        return None
    return match.group("tenant_slug")


class TenantPathMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        runtime_schema_switching = (
            settings.DJANGO_TENANTS_ENABLED
            and hasattr(connection, "set_tenant")
            and hasattr(connection, "set_schema_to_public")
        )
        if runtime_schema_switching:
            connection.set_schema_to_public()

        tenant_slug = extract_tenant_slug(request.path_info)
        if tenant_slug is None:
            request.tenant_ctx = None
            request.tenant = None
            return self._get_response(request)

        tenant = (
            Tenant.objects.filter(slug=tenant_slug, status=Tenant.Status.ACTIVE)
            .only("id", "slug", "schema_name")
            .first()
        )
        if tenant is None:
            return HttpResponseNotFound()

        request.tenant = tenant
        request.tenant_ctx = TenantContext(
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            schema_name=tenant.schema_name,
        )

        if not runtime_schema_switching:
            return self._get_response(request)

        connection.set_tenant(tenant)
        try:
            return self._get_response(request)
        finally:
            connection.set_schema_to_public()

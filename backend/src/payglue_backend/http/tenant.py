# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import re
from collections.abc import Callable

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
        # Until PG-273 this switched the Postgres schema around the view when
        # django_tenants was enabled. It never was, in any environment, and the
        # package is gone. What the middleware does now is resolve /t/<slug>/ to
        # a tenant and hang it on the request; the isolation itself is the
        # tenant_slug column every query filters on.
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

        return self._get_response(request)

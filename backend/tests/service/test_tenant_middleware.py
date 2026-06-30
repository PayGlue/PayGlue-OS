import pytest
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from payglue_backend.core.models import TenantContext
from payglue_backend.http.tenant import TenantPathMiddleware, extract_tenant_slug
from payglue_backend.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_extract_tenant_slug_success() -> None:
    assert extract_tenant_slug("/t/acme-co/api/v1/webhooks") == "acme-co"


def test_extract_tenant_slug_non_tenant_path_returns_none() -> None:
    assert extract_tenant_slug("/api/v1/health") is None


def test_tenant_middleware_attaches_context_for_known_tenant_paths() -> None:
    tenant = Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")
    factory = RequestFactory()
    captured_tenant_ctx: list[TenantContext | None] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        captured_tenant_ctx.append(getattr(request, "tenant_ctx", None))
        return HttpResponse(status=204)

    middleware = TenantPathMiddleware(get_response)
    request = factory.get("/t/tenant-a/api/v1/auth/session")

    response = middleware(request)

    assert response.status_code == 204
    tenant_ctx = captured_tenant_ctx[0]
    assert isinstance(tenant_ctx, TenantContext)
    assert tenant_ctx is not None
    assert tenant_ctx.tenant_id == tenant.id
    assert tenant_ctx.tenant_slug == "tenant-a"
    assert tenant_ctx.schema_name == "tenant_a"


def test_tenant_middleware_returns_404_for_unknown_tenant_slug() -> None:
    factory = RequestFactory()

    def get_response(request: HttpRequest) -> HttpResponse:
        del request
        return HttpResponse(status=204)

    middleware = TenantPathMiddleware(get_response)
    request = factory.get("/t/missing-tenant/api/v1/auth/session")

    response = middleware(request)

    assert response.status_code == 404


def test_tenant_middleware_returns_404_for_non_active_tenant() -> None:
    Tenant.objects.create(
        slug="suspended-tenant",
        schema_name="suspended_tenant",
        status=Tenant.Status.SUSPENDED,
    )
    factory = RequestFactory()

    def get_response(request: HttpRequest) -> HttpResponse:
        del request
        return HttpResponse(status=204)

    middleware = TenantPathMiddleware(get_response)
    request = factory.get("/t/suspended-tenant/api/v1/auth/session")

    response = middleware(request)

    assert response.status_code == 404


def test_tenant_middleware_is_noop_for_non_tenant_paths() -> None:
    factory = RequestFactory()
    captured_tenant_ctx: list[object] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        captured_tenant_ctx.append(getattr(request, "tenant_ctx", None))
        return HttpResponse(status=204)

    middleware = TenantPathMiddleware(get_response)
    request = factory.get("/api/v1/auth/session")

    response = middleware(request)

    assert response.status_code == 204
    assert captured_tenant_ctx == [None]


def test_tenant_middleware_uses_path_info_for_prefixed_deployments() -> None:
    Tenant.objects.create(slug="tenant-real", schema_name="tenant_real")
    factory = RequestFactory()
    captured_tenant_slug: list[str | None] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        tenant_ctx = getattr(request, "tenant_ctx", None)
        captured_tenant_slug.append(
            None if tenant_ctx is None else tenant_ctx.tenant_slug
        )
        return HttpResponse(status=204)

    middleware = TenantPathMiddleware(get_response)
    request = factory.get("/app/t/ignored/api/v1/session")
    request.path_info = "/t/tenant-real/api/v1/session"

    response = middleware(request)

    assert response.status_code == 204
    assert captured_tenant_slug == ["tenant-real"]

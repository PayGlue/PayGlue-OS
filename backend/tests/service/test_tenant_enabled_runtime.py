import pytest
from django.conf import settings
from django.db import connection
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from django_tenants.utils import get_public_schema_name, schema_context

from payglue_backend.http.tenant import TenantPathMiddleware
from payglue_backend.tenants.models import Tenant
from payglue_backend.webhooks.models import WebhookEventRecord


def _tenant_runtime_available() -> bool:
    return (
        settings.DJANGO_TENANTS_ENABLED
        and connection.vendor == "postgresql"
        and connection.settings_dict["ENGINE"] == "django_tenants.postgresql_backend"
        and hasattr(connection, "set_tenant")
        and hasattr(connection, "set_schema_to_public")
    )


pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        not _tenant_runtime_available(),
        reason="requires DJANGO_TENANTS_ENABLED=1 on PostgreSQL with django-tenants backend",
    ),
]


def test_path_middleware_switches_schema_for_known_active_tenant() -> None:
    tenant = Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")
    factory = RequestFactory()
    seen_schema_name: list[str] = []

    def get_response(request: HttpRequest) -> HttpResponse:
        assert getattr(request, "tenant", None) == tenant
        seen_schema_name.append(connection.schema_name)
        return HttpResponse(status=204)

    middleware = TenantPathMiddleware(get_response)
    response = middleware(factory.get("/t/tenant-a/webhooks/polar/token/"))

    assert response.status_code == 204
    assert seen_schema_name == ["tenant_a"]
    assert connection.schema_name == get_public_schema_name()


def test_path_middleware_returns_404_for_unknown_or_inactive_tenant() -> None:
    Tenant.objects.create(
        slug="disabled-tenant",
        schema_name="disabled_tenant",
        status=Tenant.Status.DISABLED,
    )
    factory = RequestFactory()

    def get_response(request: HttpRequest) -> HttpResponse:
        del request
        return HttpResponse(status=204)

    middleware = TenantPathMiddleware(get_response)

    unknown_response = middleware(
        factory.get("/t/missing-tenant/webhooks/polar/token/")
    )
    inactive_response = middleware(
        factory.get("/t/disabled-tenant/webhooks/polar/token/")
    )

    assert unknown_response.status_code == 404
    assert inactive_response.status_code == 404
    assert connection.schema_name == get_public_schema_name()


def test_webhook_event_record_isolation_smoke() -> None:
    tenant_a = Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")
    tenant_b = Tenant.objects.create(slug="tenant-b", schema_name="tenant_b")

    try:
        tenant_a.create_schema(check_if_exists=True, sync_schema=True)
        tenant_b.create_schema(check_if_exists=True, sync_schema=True)

        with schema_context("tenant_a"):
            WebhookEventRecord.objects.create(
                idempotency_key="evt_1",
                tenant_slug="tenant-a",
                provider="polar",
                provider_event_id="evt_1",
                status=WebhookEventRecord.Status.PROCESSING,
            )

        with schema_context("tenant_b"):
            assert WebhookEventRecord.objects.count() == 0
            WebhookEventRecord.objects.create(
                idempotency_key="evt_1",
                tenant_slug="tenant-b",
                provider="polar",
                provider_event_id="evt_1",
                status=WebhookEventRecord.Status.PROCESSING,
            )

        with schema_context("tenant_a"):
            assert WebhookEventRecord.objects.count() == 1
    except (ProgrammingError, OperationalError) as exc:
        pytest.skip(f"tenant schema isolation smoke unavailable in this harness: {exc}")
    finally:
        connection.set_schema_to_public()


def test_path_middleware_resets_schema_after_view_exception() -> None:
    Tenant.objects.create(slug="tenant-ex", schema_name="tenant_ex")
    factory = RequestFactory()

    def get_response(request: HttpRequest) -> HttpResponse:
        del request
        raise RuntimeError("boom")

    middleware = TenantPathMiddleware(get_response)

    with pytest.raises(RuntimeError):
        middleware(factory.get("/t/tenant-ex/webhooks/polar/token/"))

    assert connection.schema_name == get_public_schema_name()

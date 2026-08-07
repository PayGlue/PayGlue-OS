# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-196: the Django security middleware must actually emit its headers, and
the Bearer-token API must keep working without a CSRF token (CsrfViewMiddleware
only guards the session-based admin, not the csrf_exempt DRF views)."""
import json

import pytest
from django.test import Client

from payglue_backend.tenants.models import Tenant

pytestmark = pytest.mark.django_db


def test_clickjacking_and_nosniff_headers_present() -> None:
    # Any response goes through SecurityMiddleware + XFrameOptionsMiddleware.
    # Deliberately a route every build has: this file is one of the tests that
    # runs against the published tree too, where the admin console does not
    # exist and its own settings module is maintained separately.
    resp = Client().get("/health")
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"


def test_bearer_api_post_is_not_blocked_by_csrf() -> None:
    # No auth header + no CSRF token: DRF returns 401/403 from *authentication*,
    # never a Django CSRF 403 ("CSRF token missing"). Adding CsrfViewMiddleware
    # must not turn API POSTs into CSRF failures.
    Tenant.objects.create(slug="acme", schema_name="acme")
    resp = Client().post(
        "/t/acme/api/v1/mappings",
        data=json.dumps({"payment_provider": "polar"}),
        content_type="application/json",
    )
    assert resp.status_code in (401, 403)
    body = resp.content.decode().lower()
    assert "csrf" not in body

"""The Digistore24 products endpoint.

Kept apart from test_tenant_integrations_api.py because its route lives in
config/urls.py, which PayGlue-OS maintains by hand and gets at release time.
scripts/sync-oss.sh leaves this file out until then.
"""
import pytest
from django.test import Client

from payglue_backend.tenants.models import Tenant, TenantMembership

# A sibling module: pytest puts tests/service on sys.path (no __init__.py).
from test_tenant_integrations_api import _auth_headers, _MemoryCredentialProvider

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _seed_tenant_registry() -> None:
    Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")


def test_digistore24_products_use_the_public_order_form(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Client()
    headers = _auth_headers(monkeypatch, TenantMembership.Role.OWNER)
    provider = _MemoryCredentialProvider({"api_key": "123-abc"})
    monkeypatch.setattr("payglue_backend.webhooks.wiring.get_credential_provider", lambda: provider)
    monkeypatch.setattr(
        "payglue_backend.webhooks.adapters.digistore24.ds24_call",
        lambda function, api_key, params=None: {
            "products": [
                {
                    "id": "768495",
                    "name": "Inner Circle",
                    "is_active": "Y",
                    "is_deleted": "N",
                    "orderform_customer_url": "https://www.digistore24.com/product/768495",
                    "orderform_preview_url": "https://www.digistore24.com/product/768495?testpay=SECRET",
                },
                {"id": "1", "name": "Old", "is_active": "N", "is_deleted": "N"},
                {"id": "2", "name": "Gone", "is_active": "Y", "is_deleted": "Y"},
            ]
        },
    )

    response = client.get("/t/tenant-a/api/v1/billing/digistore24-products", **headers)

    assert response.status_code == 200
    assert response.json() == {
        "products": [
            {
                "id": "768495",
                "name": "Inner Circle",
                "checkout_url": "https://www.digistore24.com/product/768495",
            }
        ],
        "has_token": True,
    }
    assert "testpay" not in response.content.decode()

"""Migration webhooks 0029 rebuilds the credential note a second Save erased."""
import importlib

import pytest
from django.apps import apps

from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.credentials import DbCredentialProvider
from payglue_backend.webhooks.models import IntegrationConfig

pytestmark = pytest.mark.django_db

migration = importlib.import_module("payglue_backend.webhooks.migrations.0029_restore_credential_ref")


def test_a_connection_with_credentials_but_no_note_gets_it_back() -> None:
    DbCredentialProvider().set_credentials(
        TenantContext(tenant_slug="tenant-a"), "gumroad", {"access_token": "secret-token", "application_secret": "s"}
    )
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a", provider_key="gumroad", enabled=True, provider_type="gumroad", metadata={"health": {"ok": True}}
    )
    IntegrationConfig.objects.create(
        tenant_slug="tenant-b", provider_key="polar", enabled=True, provider_type="polar",
        metadata={"credential_ref": {"backend": "db", "masked_keys": ["api_token"]}},
    )
    IntegrationConfig.objects.create(tenant_slug="tenant-c", provider_key="paddle", enabled=True, provider_type="paddle", metadata={})

    migration.restore(apps, None)

    gumroad = IntegrationConfig.objects.get(tenant_slug="tenant-a").metadata
    assert gumroad["credential_ref"]["masked_keys"] == ["access_token", "application_secret"]
    assert gumroad["health"] == {"ok": True}
    assert "secret-token" not in str(gumroad)
    # An existing note stays, and a connection without credentials gets none.
    assert IntegrationConfig.objects.get(tenant_slug="tenant-b").metadata["credential_ref"]["masked_keys"] == ["api_token"]
    assert "credential_ref" not in IntegrationConfig.objects.get(tenant_slug="tenant-c").metadata

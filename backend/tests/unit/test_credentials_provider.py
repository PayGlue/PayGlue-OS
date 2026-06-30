from django.test import override_settings
import pytest

from payglue_backend.core.errors import MissingCredentialsError
from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.credentials import EnvCredentialProvider


def test_env_credential_provider_requires_tenant_specific_credentials_by_default() -> (
    None
):
    provider = EnvCredentialProvider(
        config={"*": {"polar": {"webhook_secret": "shared-secret"}}}
    )

    with pytest.raises(MissingCredentialsError):
        provider.get_credentials(TenantContext(tenant_slug="tenant-a"), "polar")


@override_settings(PROVIDER_CREDENTIALS_ALLOW_WILDCARD=True)
def test_env_credential_provider_can_use_wildcard_when_enabled() -> None:
    provider = EnvCredentialProvider(
        config={"*": {"polar": {"webhook_secret": "shared-secret"}}}
    )

    credentials = provider.get_credentials(
        TenantContext(tenant_slug="tenant-a"), "polar"
    )

    assert credentials["webhook_secret"] == "shared-secret"


@override_settings(PROVIDER_CREDENTIALS_ALLOW_WILDCARD=True)
def test_env_credential_provider_can_fallback_to_global_provider_when_tenant_partial() -> (
    None
):
    provider = EnvCredentialProvider(
        config={
            "tenant-a": {"ghost": {"admin_api_key": "x:y"}},
            "*": {"polar": {"webhook_secret": "shared-secret"}},
        }
    )

    credentials = provider.get_credentials(
        TenantContext(tenant_slug="tenant-a"), "polar"
    )

    assert credentials["webhook_secret"] == "shared-secret"

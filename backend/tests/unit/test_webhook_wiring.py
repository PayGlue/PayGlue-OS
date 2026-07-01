from django.test import override_settings
from django.core.exceptions import ImproperlyConfigured
import pytest

from payglue_backend.webhooks import wiring
from payglue_backend.webhooks.credentials import EnvCredentialProvider
from payglue_backend.webhooks.models import IntegrationConfig
from payglue_backend.webhooks.resolver import DbProductMappingResolver


@override_settings(
    WEBHOOK_ENDPOINT_TOKENS={"tenant-a": {"polar": "tenant-token"}},
    WEBHOOK_ALLOW_GLOBAL_ENDPOINT_TOKEN=False,
    WEBHOOK_ENDPOINT_TOKEN="global-token",
)
def test_validate_endpoint_token_prefers_tenant_provider_mapping() -> None:
    assert wiring.validate_endpoint_token("tenant-a", "polar", "tenant-token") is True
    assert wiring.validate_endpoint_token("tenant-a", "polar", "wrong") is False


@override_settings(
    WEBHOOK_ENDPOINT_TOKENS={},
    WEBHOOK_ALLOW_GLOBAL_ENDPOINT_TOKEN=False,
    WEBHOOK_ENDPOINT_TOKEN="global-token",
)
def test_validate_endpoint_token_rejects_when_no_tenant_token_and_global_disabled() -> (
    None
):
    assert wiring.validate_endpoint_token("tenant-a", "polar", "global-token") is False


@override_settings(
    WEBHOOK_ENDPOINT_TOKENS={},
    WEBHOOK_ALLOW_GLOBAL_ENDPOINT_TOKEN=True,
    WEBHOOK_ENDPOINT_TOKEN="global-token",
)
def test_validate_endpoint_token_can_use_global_fallback_when_explicitly_enabled() -> (
    None
):
    assert wiring.validate_endpoint_token("tenant-a", "polar", "global-token") is True


def test_wiring_builds_orchestrator_with_db_mapping_resolver() -> None:
    wiring._orchestrator = None
    wiring._credential_provider = None

    orchestrator = wiring.get_webhook_orchestrator()

    assert isinstance(orchestrator._mapping_resolver, DbProductMappingResolver)


def test_wiring_exposes_supported_provider_sets() -> None:
    assert "polar" in wiring.get_supported_payment_provider_keys()
    assert "ghost" in wiring.get_supported_cms_provider_keys()


@override_settings(FIRESTORE_CREDENTIALS_ENABLED=False, DB_CREDENTIALS_ENABLED=False)
def test_get_credential_provider_defaults_to_env_provider() -> None:
    wiring._credential_provider = None

    provider = wiring.get_credential_provider()

    assert isinstance(provider, EnvCredentialProvider)


@override_settings(
    FIRESTORE_CREDENTIALS_ENABLED=True, CREDENTIAL_ENCRYPTION_KEY="invalid"
)
def test_get_credential_provider_uses_firestore_when_enabled(monkeypatch) -> None:
    wiring._credential_provider = None

    class StubFirestoreProvider:
        pass

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.FirestoreCredentialProvider",
        lambda: StubFirestoreProvider(),
    )
    provider = wiring.get_credential_provider()

    assert isinstance(provider, StubFirestoreProvider)


@override_settings(FIRESTORE_CREDENTIALS_ENABLED=True)
def test_get_credential_provider_raises_improperly_configured_when_firestore_init_fails(
    monkeypatch,
) -> None:
    wiring._credential_provider = None

    def _raise() -> object:
        raise ValueError("bad config")

    monkeypatch.setattr(
        "payglue_backend.webhooks.wiring.FirestoreCredentialProvider",
        _raise,
    )

    with pytest.raises(ImproperlyConfigured):
        wiring.get_credential_provider()


@pytest.mark.django_db
def test_get_tenant_cms_provider_key_falls_back_for_unsupported_config() -> None:
    IntegrationConfig.objects.create(
        tenant_slug="tenant-a",
        provider_key="cms",
        enabled=True,
        provider_type="unsupported-cms",
        metadata={},
    )

    provider_key = wiring.get_tenant_cms_provider_key("tenant-a")

    assert provider_key == "ghost"

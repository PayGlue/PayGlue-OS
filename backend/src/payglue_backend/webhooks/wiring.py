# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import secrets

from django.core.exceptions import ImproperlyConfigured
from django.conf import settings

from payglue_backend.core.interfaces import (
    CmsAdapter,
    CredentialProvider,
    PaymentAdapter,
)
from payglue_backend.core.orchestrator import WebhookOrchestrator
from payglue_backend.core.registry import AdapterRegistry
from payglue_backend.webhooks.adapters.ghost import (
    GhostCmsAdapter,
    UrllibHttpApiClient,
)
from payglue_backend.webhooks.adapters.lemon_squeezy import LemonSqueezyPaymentAdapter
from payglue_backend.webhooks.adapters.paypal import PayPalPaymentAdapter
from payglue_backend.webhooks.adapters.polar import PolarPaymentAdapter
from payglue_backend.webhooks.credentials import DbCredentialProvider
from payglue_backend.webhooks.credentials import EnvCredentialProvider
from payglue_backend.webhooks.credentials import FirestoreCredentialProvider
from payglue_backend.webhooks.idempotency import DbIdempotencyStore
from payglue_backend.webhooks.models import IntegrationConfig
from payglue_backend.webhooks.resolver import DbProductMappingResolver

_DEFAULT_CMS_PROVIDER_KEY = "ghost"
_SUPPORTED_PAYMENT_PROVIDER_KEYS = {"polar", "lemonsqueezy", "paypal"}
_SUPPORTED_CMS_PROVIDER_KEYS = {_DEFAULT_CMS_PROVIDER_KEY}
_orchestrator: WebhookOrchestrator | None = None
_credential_provider: CredentialProvider | None = None


def get_credential_provider() -> CredentialProvider:
    global _credential_provider
    if _credential_provider is not None:
        return _credential_provider

    if getattr(settings, "FIRESTORE_CREDENTIALS_ENABLED", False):
        try:
            _credential_provider = FirestoreCredentialProvider()
        except Exception as exc:
            raise ImproperlyConfigured(
                "FIRESTORE_CREDENTIALS_ENABLED=1 but Firestore credential provider could not initialize."
            ) from exc
    elif getattr(settings, "DB_CREDENTIALS_ENABLED", True):
        _credential_provider = DbCredentialProvider()
    else:
        _credential_provider = EnvCredentialProvider()
    return _credential_provider


def get_webhook_orchestrator() -> WebhookOrchestrator:
    global _orchestrator
    if _orchestrator is not None:
        return _orchestrator

    credential_provider = get_credential_provider()
    registry = AdapterRegistry()
    registry.register_payment(
        "polar", PolarPaymentAdapter(credential_provider=credential_provider)
    )
    registry.register_payment(
        "lemonsqueezy", LemonSqueezyPaymentAdapter(credential_provider=credential_provider)
    )
    registry.register_payment(
        "paypal", PayPalPaymentAdapter(credential_provider=credential_provider)
    )
    registry.register_cms(
        _DEFAULT_CMS_PROVIDER_KEY,
        GhostCmsAdapter(
            http_client=UrllibHttpApiClient(),
            credential_provider=credential_provider,
        ),
    )

    resolver = DbProductMappingResolver()
    _orchestrator = WebhookOrchestrator(
        adapter_registry=registry,
        mapping_resolver=resolver,
        idempotency_store=DbIdempotencyStore(),
    )
    return _orchestrator


def get_default_cms_provider_key() -> str:
    return _DEFAULT_CMS_PROVIDER_KEY


def get_supported_payment_provider_keys() -> set[str]:
    return set(_SUPPORTED_PAYMENT_PROVIDER_KEYS)


def get_supported_cms_provider_keys() -> set[str]:
    return set(_SUPPORTED_CMS_PROVIDER_KEYS)


def get_cms_adapter(provider_key: str) -> CmsAdapter:
    if provider_key == _DEFAULT_CMS_PROVIDER_KEY:
        return GhostCmsAdapter(
            http_client=UrllibHttpApiClient(),
            credential_provider=get_credential_provider(),
            provider_key=provider_key,
        )
    raise ValueError(f"Unsupported cms provider '{provider_key}'.")


def get_payment_adapter(provider_key: str) -> PaymentAdapter:
    if provider_key == "polar":
        return PolarPaymentAdapter(
            credential_provider=get_credential_provider(),
            provider_key=provider_key,
        )
    if provider_key == "lemonsqueezy":
        return LemonSqueezyPaymentAdapter(
            credential_provider=get_credential_provider(),
            provider_key=provider_key,
        )
    if provider_key == "paypal":
        return PayPalPaymentAdapter(
            credential_provider=get_credential_provider(),
            provider_key=provider_key,
        )
    raise ValueError(f"Unsupported payment provider '{provider_key}'.")


def get_tenant_cms_provider_key(tenant_slug: str) -> str:
    cms_config = IntegrationConfig.objects.filter(
        tenant_slug=tenant_slug,
        provider_key="cms",
        enabled=True,
    ).first()
    if (
        cms_config is not None
        and cms_config.provider_type
        and cms_config.provider_type in get_supported_cms_provider_keys()
    ):
        return cms_config.provider_type
    return get_default_cms_provider_key()


def validate_endpoint_token(
    tenant_slug: str, payment_provider: str, endpoint_token: str
) -> bool:
    configured_token = get_expected_endpoint_token(tenant_slug, payment_provider)
    if configured_token is None:
        return False

    return secrets.compare_digest(configured_token, endpoint_token)


def get_expected_endpoint_token(tenant_slug: str, payment_provider: str) -> str | None:
    token_mapping = getattr(settings, "WEBHOOK_ENDPOINT_TOKENS", {})
    tenant_providers = token_mapping.get(tenant_slug)
    if isinstance(tenant_providers, dict):
        provider_token = tenant_providers.get(payment_provider)
        if isinstance(provider_token, str) and provider_token:
            return provider_token

    if not getattr(settings, "WEBHOOK_ALLOW_GLOBAL_ENDPOINT_TOKEN", False):
        return None

    fallback_token = getattr(settings, "WEBHOOK_ENDPOINT_TOKEN", None)
    if isinstance(fallback_token, str) and fallback_token:
        return fallback_token

    return None

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import json
import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent.parent.parent

_secret_key = os.environ.get("DJANGO_SECRET_KEY", "")
if not _secret_key:
    raise RuntimeError(
        "DJANGO_SECRET_KEY environment variable is required and must not be empty."
    )
SECRET_KEY = _secret_key

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"


def _parse_allowed_hosts() -> list[str]:
    raw = os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,0.0.0.0,dev.payglue.io,dev2.payglue.io,hooks.payglue.io,hooks2.payglue.io",
    )
    return [host.strip() for host in raw.split(",") if host.strip()]


ALLOWED_HOSTS = _parse_allowed_hosts()

DJANGO_TENANTS_AVAILABLE = importlib.util.find_spec("django_tenants") is not None
DJANGO_TENANTS_ENABLED = (
    os.environ.get("DJANGO_TENANTS_ENABLED", "0") == "1" and DJANGO_TENANTS_AVAILABLE
)

SHARED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "payglue_backend.tenants",
]

TENANT_APPS = [
    "rest_framework",
    "payglue_backend.webhooks",
]

if DJANGO_TENANTS_ENABLED:
    SHARED_APPS = ["django_tenants", *SHARED_APPS]

INSTALLED_APPS = [*SHARED_APPS, *[app for app in TENANT_APPS if app not in SHARED_APPS]]

MIDDLEWARE = [
    "payglue_backend.http.tenant.TenantPathMiddleware",
]

ROOT_URLCONF = "payglue_backend.config.urls"

TEMPLATES: list[dict[str, object]] = []
WSGI_APPLICATION = "payglue_backend.config.wsgi.application"
ASGI_APPLICATION = "payglue_backend.config.asgi.application"


def _build_database_settings() -> dict[str, dict[str, object]]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        if parsed.scheme in {"postgres", "postgresql"}:
            return {
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": parsed.path.lstrip("/"),
                    "USER": parsed.username or "",
                    "PASSWORD": parsed.password or "",
                    "HOST": parsed.hostname or "localhost",
                    "PORT": str(parsed.port or 5432),
                }
            }
        if parsed.scheme == "sqlite":
            return {
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": parsed.path,
                }
            }

    pg_name = os.environ.get("PGDATABASE") or os.environ.get("POSTGRES_DB")
    if pg_name:
        return {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": pg_name,
                "USER": os.environ.get("PGUSER")
                or os.environ.get("POSTGRES_USER")
                or "postgres",
                "PASSWORD": os.environ.get("PGPASSWORD")
                or os.environ.get("POSTGRES_PASSWORD")
                or "postgres",
                "HOST": os.environ.get("PGHOST") or "localhost",
                "PORT": os.environ.get("PGPORT") or "5432",
            }
        }

    return {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


DATABASES = _build_database_settings()

if (
    DJANGO_TENANTS_ENABLED
    and DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql"
):
    raise RuntimeError(
        "DJANGO_TENANTS_ENABLED requires a PostgreSQL database configuration."
    )

if (
    DJANGO_TENANTS_ENABLED
    and DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
):
    DATABASES["default"]["ENGINE"] = "django_tenants.postgresql_backend"
    DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

TENANT_MODEL = "tenants.Tenant"
TENANT_DOMAIN_MODEL = "tenants.TenantDomain"
PUBLIC_SCHEMA_NAME = "public"


def _parse_webhook_endpoint_tokens() -> dict[str, dict[str, str]]:
    raw = os.environ.get("WEBHOOK_ENDPOINT_TOKENS", "")
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    valid: dict[str, dict[str, str]] = {}
    for tenant_slug, providers in parsed.items():
        if not isinstance(tenant_slug, str) or not isinstance(providers, dict):
            continue
        provider_tokens: dict[str, str] = {}
        for provider, token in providers.items():
            if isinstance(provider, str) and isinstance(token, str) and token:
                provider_tokens[provider] = token
        if provider_tokens:
            valid[tenant_slug] = provider_tokens

    return valid


WEBHOOK_ENDPOINT_TOKEN = os.environ.get("WEBHOOK_ENDPOINT_TOKEN")
WEBHOOK_ENDPOINT_TOKENS = _parse_webhook_endpoint_tokens()
WEBHOOK_ALLOW_GLOBAL_ENDPOINT_TOKEN = (
    os.environ.get("WEBHOOK_ALLOW_GLOBAL_ENDPOINT_TOKEN", "0") == "1"
)
FIREBASE_AUTH_ENABLED = os.environ.get("FIREBASE_AUTH_ENABLED", "0") == "1"
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
SUPABASE_JWKS_URL = os.environ.get("SUPABASE_JWKS_URL", "")
SUPABASE_JWKS_KEYS = os.environ.get("SUPABASE_JWKS_KEYS", "")
PREFINERY_INVITATION_DECODER_KEY = os.environ.get("PREFINERY_INVITATION_DECODER_KEY", "")
PREFINERY_INVITATION_SHORTCODE_LENGTH = int(
    os.environ.get("PREFINERY_INVITATION_SHORTCODE_LENGTH", "10")
)
PREFINERY_INVITE_GATE_ENABLED = (
    os.environ.get("PREFINERY_INVITE_GATE_ENABLED", "1") == "1"
)
POLAR_API_KEY = os.environ.get("POLAR_API_KEY", "")
POLAR_ORGANIZATION_ID = os.environ.get("POLAR_ORGANIZATION_ID", "")
POLAR_SANDBOX_API_KEY = os.environ.get("POLAR_SANDBOX_API_KEY", "")
POLAR_SANDBOX_ORGANIZATION_ID = os.environ.get("POLAR_SANDBOX_ORGANIZATION_ID", "")
DEV_BYPASS_EMAILS: set[str] = {
    e.strip().lower()
    for e in os.environ.get("DEV_BYPASS_EMAILS", "dev@payglue.io").split(",")
    if e.strip()
}


def _parse_provider_credentials() -> dict[str, dict[str, dict[str, str]]]:
    raw = os.environ.get("PROVIDER_CREDENTIALS", "")
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    result: dict[str, dict[str, dict[str, str]]] = {}
    for tenant_slug, providers in parsed.items():
        if not isinstance(tenant_slug, str) or not isinstance(providers, dict):
            continue

        normalized_providers: dict[str, dict[str, str]] = {}
        for provider_key, credentials in providers.items():
            if not isinstance(provider_key, str) or not isinstance(credentials, dict):
                continue

            normalized_credentials = {
                key: value
                for key, value in credentials.items()
                if isinstance(key, str) and isinstance(value, str) and value
            }
            if normalized_credentials:
                normalized_providers[provider_key] = normalized_credentials

        if normalized_providers:
            result[tenant_slug] = normalized_providers

    return result


PROVIDER_CREDENTIALS = _parse_provider_credentials()
PROVIDER_CREDENTIALS_ALLOW_WILDCARD = (
    os.environ.get("PROVIDER_CREDENTIALS_ALLOW_WILDCARD", "0") == "1"
)
FIRESTORE_CREDENTIALS_ENABLED = (
    os.environ.get("FIRESTORE_CREDENTIALS_ENABLED", "0") == "1"
)
FIRESTORE_CREDENTIALS_COLLECTION = os.environ.get(
    "FIRESTORE_CREDENTIALS_COLLECTION", "tenant_provider_credentials"
)
CREDENTIAL_ENCRYPTION_KEY = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
INTERNAL_API_SECRET = os.environ.get("INTERNAL_API_SECRET", "")
DB_CREDENTIALS_ENABLED = os.environ.get("DB_CREDENTIALS_ENABLED", "1") == "1"
WEBHOOK_MAX_BODY_BYTES = int(os.environ.get("WEBHOOK_MAX_BODY_BYTES", "65536"))
WEBHOOK_HEADER_MAX_CHARS = int(os.environ.get("WEBHOOK_HEADER_MAX_CHARS", "512"))
WEBHOOK_PROCESSING_TIMEOUT_SECONDS = int(
    os.environ.get("WEBHOOK_PROCESSING_TIMEOUT_SECONDS", "900")
)

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


RUNNING_TESTS = any("pytest" in arg for arg in sys.argv)
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND", "redis://localhost:6379/1"
)
CELERY_TASK_ALWAYS_EAGER = (
    os.environ.get("CELERY_TASK_ALWAYS_EAGER", "1" if RUNNING_TESTS else "0") == "1"
)
CELERY_TASK_EAGER_PROPAGATES = (
    os.environ.get("CELERY_TASK_EAGER_PROPAGATES", "1" if RUNNING_TESTS else "0") == "1"
)

REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "payglue_backend.http.throttling.DynamicScopedRateThrottle"
    ],
    "DEFAULT_THROTTLE_RATES": {
        "auth_session": os.environ.get("DRF_THROTTLE_AUTH_SESSION", "60/minute"),
        "auth_invitation_validate": os.environ.get(
            "DRF_THROTTLE_AUTH_INVITATION_VALIDATE", "30/minute"
        ),
        "webhook_ingest": os.environ.get("DRF_THROTTLE_WEBHOOK_INGEST", "120/minute"),
        "integration_credentials_write": os.environ.get(
            "DRF_THROTTLE_INTEGRATION_CREDENTIALS_WRITE", "30/minute"
        ),
        "integration_health": os.environ.get(
            "DRF_THROTTLE_INTEGRATION_HEALTH", "20/minute"
        ),
        "paywall_check": os.environ.get("DRF_THROTTLE_PAYWALL_CHECK", "60/minute"),
    },
}

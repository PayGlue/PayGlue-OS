# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
#
# HAND-MAINTAINED in the OSS repo (sync script BACKEND_NEVER_SYNC_PATHS).
# Derived from the private settings.py minus everything the internal admin
# console needs (Unfold, django.contrib.admin, sessions, OTP, templates,
# staticfiles). When the private repo gains env vars or defaults, port them
# here by hand as part of the next release.
import json
import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import urlparse



BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
_running_tests = any("pytest" in arg for arg in sys.argv)

_secret_key = os.environ.get("DJANGO_SECRET_KEY", "")
if not _secret_key:
    if DEBUG or _running_tests:
        import warnings
        warnings.warn(
            "DJANGO_SECRET_KEY is not set — using insecure dev placeholder. "
            "Set DJANGO_SECRET_KEY before running in production.",
            stacklevel=2,
        )
        _secret_key = "dev-only-insecure-do-not-use-in-production"
    else:
        raise RuntimeError(
            "DJANGO_SECRET_KEY environment variable is required and must not be empty."
        )
SECRET_KEY = _secret_key


def _parse_allowed_hosts() -> list[str]:
    raw = os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,0.0.0.0,dev.payglue.io,dev2.payglue.io,hooks.payglue.io,hooks2.payglue.io",
    )
    return [host.strip() for host in raw.split(",") if host.strip()]


ALLOWED_HOSTS = _parse_allowed_hosts()

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = [
    f"https://{host}"
    for host in ALLOWED_HOSTS
    if host not in {"localhost", "127.0.0.1", "0.0.0.0"}
]

# --- Security headers / cookies (PG-196) ---------------------------------
# The admin console must never be framed (clickjacking), and responses must
# not be MIME-sniffed. Safe in every environment.
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

# HTTPS-only concerns are enforced at the Cloudflare edge; behind the proxy
# we only turn on the cookie-secure flags and emit HSTS in production (with
# DEBUG off), so local http development still works. SECURE_SSL_REDIRECT is
# left off deliberately -- the edge already redirects, and enabling it behind
# the proxy risks redirect loops.
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

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
    # SecurityMiddleware for the generic hardening headers (nosniff, HSTS).
    # The private repo carries the full session/CSRF/OTP stack for its admin
    # console; this API-only backend needs none of it.
    "django.middleware.security.SecurityMiddleware",
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
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
# Supabase's publishable key (sb_publishable_*), the same one the frontend
# ships in its bundle. Needed as the `apikey` header on
# Supabase auth calls; authorisation itself comes from the user's own JWT.
# Deliberately not the service-role key: some Supabase endpoints grant elevated
# behaviour based on the apikey, and a step-up check must never be one of them.
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")

# PostHog shared-dashboard URL embedded in the internal admin's Analytics
# page (Settings > Sharing > Copy public link on the PostHog dashboard).
# Not a secret -- it's a public, unguessable-token URL -- but kept
# configurable via env var so it can be swapped without a deploy.
POSTHOG_SHARED_DASHBOARD_URL = os.environ.get(
    "POSTHOG_SHARED_DASHBOARD_URL",
    "https://eu.posthog.com/shared/7Wwj4IIgjZ_XapnU3CAZ3-KoGdse7A",
)
POLAR_API_KEY = os.environ.get("POLAR_API_KEY", "")
POLAR_ORGANIZATION_ID = os.environ.get("POLAR_ORGANIZATION_ID", "")
POLAR_SANDBOX_API_KEY = os.environ.get("POLAR_SANDBOX_API_KEY", "")
POLAR_SANDBOX_ORGANIZATION_ID = os.environ.get("POLAR_SANDBOX_ORGANIZATION_ID", "")
CREEM_API_KEY = os.environ.get("CREEM_API_KEY", "")
CREEM_SANDBOX_API_KEY = os.environ.get("CREEM_SANDBOX_API_KEY", "")
CREEM_WEBHOOK_SECRET = os.environ.get("CREEM_WEBHOOK_SECRET", "")
CREEM_SANDBOX_WEBHOOK_SECRET = os.environ.get("CREEM_SANDBOX_WEBHOOK_SECRET", "")

# Transactional email via Resend's HTTPS API -- see PG-182/PG-202.
# NOT SMTP: found live that Railway blocks outbound SMTP (25/465/587), so
# smtp.resend.com never connected -- socket.connect() blocked until gunicorn's
# worker timeout killed the request, and no mail ever reached Resend. The REST
# API is plain HTTPS/443 and works. RESEND_API_KEY stays the credential.
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "payglue_backend.core.email_backend.ResendAPIEmailBackend"
)
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")

# PG-208: when set, ResendAPIEmailBackend rewrites every recipient to this one
# address. Meant for staging, where seeded accounts carry invented addresses:
# the nightly cron would otherwise send lifecycle mail to them, and the bounces
# would land on payglue.io's sending reputation and hurt real customer mail.
# Empty in production, and it must stay that way.
EMAIL_REDIRECT_TO = os.environ.get("EMAIL_REDIRECT_TO", "")
# team@, not noreply@: the onboarding mails ask people to hit reply and say
# "I read every email myself", which a no-reply sender quietly contradicts.
# Resend verifies the domain rather than each address, so this needs no new
# sender setup -- but it does mean replies now land in a real inbox.
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "PayGlue <team@payglue.io>")
# PG-190: where send_lifecycle_emails alerts André when a subscription's
# Creem status is ambiguous (past_due/unpaid/paused/fetch failure) rather
# than a confirmed cancellation -- an internal ops notification, not a
# customer-facing LifecycleEmailTemplate.
INTERNAL_ADMIN_EMAIL = os.environ.get("INTERNAL_ADMIN_EMAIL", "team@payglue.io")

# Support requests from the dashboard open an issue on this Linear team, so a
# request has a reference number without us paying for Linear Ask. All three
# are optional: unset, support still works and simply has no ticket number.
LINEAR_API_KEY = os.environ.get("LINEAR_API_KEY", "")
LINEAR_SUPPORT_TEAM_ID = os.environ.get("LINEAR_SUPPORT_TEAM_ID", "")
LINEAR_SUPPORT_LABEL_ID = os.environ.get("LINEAR_SUPPORT_LABEL_ID", "")
LINEAR_SUPPORT_PROJECT_ID = os.environ.get("LINEAR_SUPPORT_PROJECT_ID", "")

# PG-194 (GDPR): webhook event logs (which hold end-customer PII in the raw
# provider payload) and public audit events are auto-purged after this many
# days by the purge_expired_logs command. The dashboard's Events page shows a
# matching notice. Env-overridable, but keep it aligned with the notice copy.
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "90"))
# Data minimisation: raw provider payloads (PII) on PROCESSED webhook events
# are scrubbed after this shorter window -- they're never re-read once an event
# is terminally processed. See purge_expired_logs.
PAYLOAD_RAW_RETENTION_DAYS = int(os.environ.get("PAYLOAD_RAW_RETENTION_DAYS", "7"))
DEV_BYPASS_EMAILS: set[str] = {
    e.strip().lower()
    for e in os.environ.get("DEV_BYPASS_EMAILS", "dev@payglue.io").split(",")
    if e.strip()
}

# Lets any email through AccessValidateView's invite gate without a real
# Creem/Polar purchase, for signup testing (PG-142). Unset by default --
# only takes effect once a real secret is configured in Railway. Never
# shipped to the frontend; the invite-code field just does a normal POST
# to /access/validate like any other code, so a value has to be typed in
# by someone who actually knows it, not read out of the public JS bundle.
DEV_BYPASS_LICENSE_KEY = os.environ.get("DEV_BYPASS_LICENSE_KEY", "")


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
        # PG-203: step-up. Tight on purpose -- these gate destructive actions,
        # and the request leg also sends mail, so it must not be a free
        # mail-flooding lever pointed at somebody's inbox.
        "auth_step_up_request": os.environ.get("DRF_THROTTLE_AUTH_STEP_UP_REQUEST", "5/minute"),
        "auth_step_up_verify": os.environ.get("DRF_THROTTLE_AUTH_STEP_UP_VERIFY", "10/minute"),
        "auth_mfa_backup_code_verify": os.environ.get(
            "DRF_THROTTLE_AUTH_MFA_BACKUP_CODE_VERIFY", "10/minute"
        ),
    },
}

# Unhandled exceptions must always be visible in production logs -- Django's
# own DEFAULT_LOGGING gates its console handler behind require_debug_true,
# so with DEBUG=False (correct for prod) every unhandled exception (and any
# of our own logger.exception()/logger.error() calls) was silently dropped,
# not even reaching stdout/stderr. Found this the hard way debugging a
# Cloudflare 502 with zero trace anywhere (PG-150 follow-up).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

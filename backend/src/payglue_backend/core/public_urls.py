# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Where this installation is reachable from the outside.

Every link we put in an email, and every URL we hand to a payment provider, has
to point at the installation that produced it. These used to be literal
payglue.io addresses scattered across the email templates, which meant a
self-hosted install sent its own customers to our dashboard (PG-238).

Emails are the awkward case: they are sent from cron jobs, where no request
exists, so there is nothing to derive an origin from. `PUBLIC_APP_BASE_URL` has
to be configured for links to work at all. When it is not, `app_url` returns an
empty string and callers leave the link out rather than render one that goes
somewhere wrong.
"""

from urllib.parse import urlsplit

from django.conf import settings


def app_base() -> str:
    """Dashboard origin, without a trailing slash. Empty when unconfigured."""
    return (getattr(settings, "PUBLIC_APP_BASE_URL", "") or "").strip().rstrip("/")


def api_base() -> str:
    """Backend origin, without a trailing slash. Empty when unconfigured."""
    return (getattr(settings, "PUBLIC_API_BASE_URL", "") or "").strip().rstrip("/")


def app_url(path: str = "") -> str:
    """Absolute dashboard URL, or empty when the dashboard address is unknown.

    Callers must treat an empty result as "no link available" rather than
    falling back to a relative path: these end up in emails, where a relative
    path resolves against the mail client and goes nowhere.
    """
    base = app_base()
    if not base:
        return ""
    if not path:
        return base
    return f"{base}/{path.lstrip('/')}"


def app_host() -> str:
    """Dashboard hostname without scheme or port, for allowlist comparisons."""
    base = app_base()
    if not base:
        return ""
    return urlsplit(base).hostname or ""

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""
Polar API calls for signup access validation.

Validates a Polar checkout session or license key and returns the
customer email associated with it, so we can create an InvitationGrant.
"""
import json
from dataclasses import dataclass
from urllib import error, request


POLAR_API_BASE = "https://api.polar.sh"
POLAR_SANDBOX_API_BASE = "https://sandbox-api.polar.sh"


@dataclass(frozen=True)
class AccessValidationResult:
    email: str


class PolarAccessError(Exception):
    pass


_HEADERS = {"User-Agent": "PayGlue/1.0 (https://payglue.io)"}


def _get(url: str, api_key: str) -> dict:
    req = request.Request(
        url=url,
        headers={**_HEADERS, "Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        raise PolarAccessError(f"Polar API {exc.code}: {body}") from exc


def _patch(url: str, api_key: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        url=url,
        data=data,
        headers={
            **_HEADERS,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PATCH",
    )
    try:
        with request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        raise PolarAccessError(f"Polar API {exc.code}: {body}") from exc


def _post(url: str, api_key: str, body: dict, _redirects: int = 3) -> dict:
    data = json.dumps(body).encode("utf-8")
    headers = {
        **_HEADERS,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    req = request.Request(url=url, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        if exc.code in (307, 308) and _redirects > 0:
            location = exc.headers.get("Location")
            if location:
                return _post(location, api_key, body, _redirects - 1)
        body_text = exc.read().decode("utf-8") if exc.fp else ""
        raise PolarAccessError(f"Polar API {exc.code}: {body_text}") from exc


def validate_checkout(checkout_id: str, api_key: str, sandbox: bool = False) -> AccessValidationResult:
    """Validate a Polar checkout session ID and return the customer email."""
    base = POLAR_SANDBOX_API_BASE if sandbox else POLAR_API_BASE
    data = _get(f"{base}/v1/checkouts/custom/{checkout_id}", api_key)

    status = data.get("status")
    if status not in ("confirmed", "succeeded"):
        raise PolarAccessError(
            f"Checkout is not completed (status={status!r}). "
            "Please complete your purchase first."
        )

    email = (data.get("customer_email") or "").strip().lower()
    if not email:
        raise PolarAccessError("No customer email found on checkout.")

    return AccessValidationResult(email=email)


def validate_license_key(license_key: str, api_key: str, organization_id: str, sandbox: bool = False) -> AccessValidationResult:
    """Validate a Polar license key and return the customer email."""
    base = POLAR_SANDBOX_API_BASE if sandbox else POLAR_API_BASE
    data = _post(
        f"{base}/v1/license-keys/validate",
        api_key,
        {"key": license_key, "organization_id": organization_id},
    )

    if not data.get("valid"):
        raise PolarAccessError("License key is not valid or has been deactivated.")

    # Polar returns the order/user info on the license key object
    email = (
        data.get("user", {}).get("email")
        or data.get("customer_email")
        or ""
    ).strip().lower()

    if not email:
        raise PolarAccessError("No customer email found on license key.")

    return AccessValidationResult(email=email)

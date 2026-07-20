# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""
Creem webhook receiver for PayGlue's own Founding Member billing.

Not to be confused with the generic multi-tenant provider adapters under
webhooks/adapters/ (GOGU-135) — this handles only Creem's checkout.completed
event for our own checkout, to pre-authorize the buyer's email (and capture
their license key, if any) via InvitationGrant. See GOGU-140.
"""
import hashlib
import hmac
import json


class CreemWebhookError(Exception):
    pass


def verify_signature(raw_body: bytes, signature_header: str, secret: str) -> bool:
    """Compare the creem-signature header against an HMAC-SHA256 of the raw body.

    Creem signs the raw request body directly (no timestamp/prefix scheme
    like Stripe) — see docs.creem.io/code/webhooks#webhook-signatures.
    """
    if not signature_header:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def parse_checkout_completed(raw_body: bytes) -> dict | None:
    """Parse a webhook payload and return the checkout object if it's checkout.completed.

    Returns None for any other event type (caller should 200 and no-op).
    The caller resolves `customer` (a string ID unless the payload happens to
    expand it inline) and `license_keys` from the returned dict.
    """
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CreemWebhookError("Invalid JSON payload.") from exc

    event_type = payload.get("eventType") or payload.get("type")
    if event_type != "checkout.completed":
        return None

    return payload.get("object") or payload


def extract_license_key(checkout: dict) -> str:
    license_keys = checkout.get("license_keys") or []
    if license_keys and isinstance(license_keys[0], dict):
        return (license_keys[0].get("key") or "").strip()
    return ""

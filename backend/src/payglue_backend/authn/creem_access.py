# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""
Creem API calls for signup access validation.

Validates a Creem checkout session and returns the customer email
associated with it, so we can create an InvitationGrant. Mirrors
polar_access.py — see GOGU-140 for the Polar-to-Creem migration.
"""
import json
from dataclasses import dataclass
from urllib import error, parse, request


CREEM_API_BASE = "https://api.creem.io"
CREEM_TEST_API_BASE = "https://test-api.creem.io"


@dataclass(frozen=True)
class AccessValidationResult:
    email: str


class CreemAccessError(Exception):
    pass


_HEADERS = {"User-Agent": "PayGlue/1.0 (https://payglue.io)"}


def _get(url: str, api_key: str) -> dict:
    req = request.Request(
        url=url,
        headers={**_HEADERS, "x-api-key": api_key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        raise CreemAccessError(f"Creem API {exc.code}: {body}") from exc


def _post(url: str, api_key: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        url=url,
        data=data,
        headers={
            **_HEADERS,
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body_text = exc.read().decode("utf-8") if exc.fp else ""
        raise CreemAccessError(f"Creem API {exc.code}: {body_text}") from exc


class CreemLicenseAlreadyUsedError(CreemAccessError):
    """Creem rejected the activation because the key is already activated or has
    hit its activation limit -- i.e. it was already redeemed."""


def activate_license(license_key: str, instance_name: str, api_key: str, sandbox: bool = False) -> dict:
    """Activate a Creem license key so Creem's own dashboard reflects that it was
    redeemed (flips it to 'active', increments the activation count, and creates
    an instance). Returns the raw license payload -- read ``instance.id`` from it
    to store the created instance for a possible later deactivation.

    Raises CreemLicenseAlreadyUsedError if the key is already activated / at its
    activation limit, and CreemAccessError for any other API failure.
    """
    base = CREEM_TEST_API_BASE if sandbox else CREEM_API_BASE
    try:
        return _post(
            f"{base}/v1/licenses/activate",
            api_key,
            {"key": license_key, "instance_name": instance_name},
        )
    except CreemAccessError as exc:
        message = str(exc).lower()
        if "already" in message or "limit" in message or "reached" in message:
            raise CreemLicenseAlreadyUsedError(str(exc)) from exc
        raise


def validate_license(
    license_key: str, api_key: str, sandbox: bool = False, instance_id: str = ""
) -> dict:
    """Validate a Creem license key (optionally against a specific instance).
    Returns the raw license payload; the caller inspects ``status``."""
    base = CREEM_TEST_API_BASE if sandbox else CREEM_API_BASE
    body: dict = {"key": license_key}
    if instance_id:
        body["instance_id"] = instance_id
    return _post(f"{base}/v1/licenses/validate", api_key, body)


def resolve_customer_email(customer: str | dict, api_key: str, sandbox: bool = False) -> str:
    """Resolve a Creem `customer` field (plain ID string, or an expanded object) to an email.

    Shared by validate_checkout() and the checkout.completed webhook handler,
    since both receive the same customer shape from Creem.
    """
    if isinstance(customer, dict):
        return (customer.get("email") or "").strip().lower()

    base = CREEM_TEST_API_BASE if sandbox else CREEM_API_BASE
    customer_query = parse.urlencode({"customer_id": customer})
    customer_data = _get(f"{base}/v1/customers?{customer_query}", api_key)
    return (customer_data.get("email") or "").strip().lower()


def validate_checkout(checkout_id: str, api_key: str, sandbox: bool = False) -> AccessValidationResult:
    """Validate a Creem checkout session ID and return the customer email.

    Two calls: GET /v1/checkouts to confirm the checkout completed and get
    the customer ID, then GET /v1/customers to resolve that ID to an email
    (Creem's checkout response embeds the customer by reference, not inline).
    """
    base = CREEM_TEST_API_BASE if sandbox else CREEM_API_BASE
    query = parse.urlencode({"checkout_id": checkout_id})
    checkout = _get(f"{base}/v1/checkouts?{query}", api_key)

    checkout_status = checkout.get("status")
    if checkout_status != "completed":
        raise CreemAccessError(
            f"Checkout is not completed (status={checkout_status!r}). "
            "Please complete your purchase first."
        )

    customer = checkout.get("customer")
    if not customer:
        raise CreemAccessError("No customer found on checkout.")

    email = resolve_customer_email(customer, api_key, sandbox=sandbox)
    if not email:
        raise CreemAccessError("No customer email found for this checkout.")

    return AccessValidationResult(email=email)


def validate_checkout_any_mode(
    checkout_id: str, sandbox_api_key: str, live_api_key: str
) -> AccessValidationResult:
    """Validate a checkout ID against sandbox then live, in that order.

    Creem's return-URL redirect appends checkout_id/order_id/customer_id but
    no mode indicator (see GOGU-140) — we can't tell from the redirect alone
    whether the purchase happened in test or live mode, so we try both API
    bases and use whichever one recognizes the checkout.
    """
    last_error: CreemAccessError | None = None
    for api_key, sandbox in ((sandbox_api_key, True), (live_api_key, False)):
        if not api_key:
            continue
        try:
            return validate_checkout(checkout_id, api_key, sandbox=sandbox)
        except CreemAccessError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise CreemAccessError("Access validation is not configured.")


def resolve_customer_id_by_email(email: str, api_key: str, sandbox: bool = False) -> str | None:
    """Look up a Creem customer_id for `email`, or None if no customer exists
    with that email on this API key (test/live are separate customer pools)."""
    base = CREEM_TEST_API_BASE if sandbox else CREEM_API_BASE
    query = parse.urlencode({"email": email})
    try:
        data = _get(f"{base}/v1/customers?{query}", api_key)
    except CreemAccessError:
        return None
    customer_id = data.get("id")
    return str(customer_id) if customer_id else None


def cancel_subscription(
    subscription_id: str, api_key: str, sandbox: bool = False, mode: str = "scheduled"
) -> dict:
    """Cancel a subscription. Default mode=scheduled cancels at the end of
    the current billing period (customer-initiated cancellation, they keep
    access through what they've already paid for). mode=immediate is for
    the plan-switch cleanup (PG-150 follow-up): when a dashboard upgrade
    creates a brand new subscription for the new plan, the old one must
    stop billing right away, not ride out its own period in parallel with
    the new one. Raises CreemAccessError on failure."""
    base = CREEM_TEST_API_BASE if sandbox else CREEM_API_BASE
    return _post(f"{base}/v1/subscriptions/{subscription_id}/cancel", api_key, {"mode": mode})


def update_subscription_product(
    subscription_id: str,
    api_key: str,
    product_id: str,
    sandbox: bool = False,
    update_behavior: str = "proration-charge-immediately",
    item_id: str | None = None,
) -> dict:
    """Switch an existing subscription to a different product in place --
    the correct way to handle a plan switch (PG-150 follow-up). Unlike
    creating a new checkout session, this never creates a second parallel
    subscription and Creem handles proration itself:
      - proration-charge-immediately: credit/charge the difference now,
        new billing cycle starts today (our default -- the customer sees
        the correct amount reflected right away instead of on some future
        invoice they might not connect back to this change)
      - proration-charge: difference applied on the next invoice instead
      - proration-none: no proration, new price applies at the current
        period's end

    item_id should be the ID of the subscription's existing line item
    (SubscriptionEntity.items[0].id) -- per Creem's OpenAPI spec, omitting
    it doesn't update the existing item, it *creates a new one*, leaving
    the subscription with both the old and new product as separate items.

    Raises CreemAccessError on failure."""
    base = CREEM_TEST_API_BASE if sandbox else CREEM_API_BASE
    item: dict[str, str] = {"product_id": product_id}
    if item_id:
        item["id"] = item_id
    return _post(
        f"{base}/v1/subscriptions/{subscription_id}",
        api_key,
        {"items": [item], "update_behavior": update_behavior},
    )


def generate_customer_portal_link(customer_id: str, api_key: str, sandbox: bool = False) -> str | None:
    """Generate a hosted Creem customer-portal link, or None on failure."""
    base = CREEM_TEST_API_BASE if sandbox else CREEM_API_BASE
    try:
        data = _post(f"{base}/v1/customers/billing", api_key, {"customer_id": customer_id})
    except CreemAccessError:
        return None
    link = data.get("customer_portal_link")
    return str(link) if link else None

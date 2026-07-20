# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Creem newsletter opt-in to PayGlue's own Ghost blog.

PayGlue as its own customer. The same adapter that syncs a customer's buyers
into their Ghost is what puts our buyers on our list, which is both the least
code and the most honest demo of the product.

Two things about the Creem payload are worth stating, because both are easy to
get wrong and neither fails loudly:

* The key is `customFields` in the checkout payload and `custom_fields` in the
  products API. A reader that knows only one spelling finds nothing and raises
  nothing. Both are checked.
* `checkbox.label` arrives empty. The consent wording lives only on the product
  definition, so proving *what* somebody agreed to means reading the product,
  not the checkout. That is why the consent text is captured at routing time
  rather than assumed to be recoverable later.
"""
import logging

from payglue_backend.core.models import (
    CanonicalCustomer,
    EntitlementInstruction,
    TenantContext,
)
from payglue_backend.tenants.models import NewsletterRouting

logger = logging.getLogger(__name__)


class NewsletterRoutingError(Exception):
    pass


def _custom_fields(payload: dict) -> list[dict]:
    """Creem spells this two different ways depending on which API you asked."""
    raw = payload.get("customFields") or payload.get("custom_fields") or []
    return [f for f in raw if isinstance(f, dict)]


def opted_in(payload: dict, field_key: str = "newsletteroptin") -> bool:
    """True only for an explicit ticked checkbox.

    Anything else -- field absent, value missing, value false -- is a no. An
    opt-in that has to be inferred is not one.
    """
    for field in _custom_fields(payload):
        if field.get("key") != field_key:
            continue
        checkbox = field.get("checkbox")
        if isinstance(checkbox, dict):
            return checkbox.get("value") is True
    return False


def store_id_of(payload: dict) -> str:
    """Creem nests the store id differently across payload shapes."""
    for candidate in (
        payload.get("store_id"),
        payload.get("storeId"),
        (payload.get("store") or {}).get("id") if isinstance(payload.get("store"), dict) else None,
        (payload.get("product") or {}).get("store_id")
        if isinstance(payload.get("product"), dict)
        else None,
    ):
        if candidate:
            return str(candidate)
    return ""


def _email_of(payload: dict) -> str:
    customer = payload.get("customer")
    if isinstance(customer, dict) and customer.get("email"):
        return str(customer["email"])
    return str(payload.get("customer_email") or payload.get("email") or "")



def _product_label(payload: dict) -> str:
    """What they actually bought, for the Ghost note.

    Without this every member reads "Product: newsletter", which says how they
    arrived but not what they paid for. The name is preferred over the id
    because the note is read by a human.
    """
    product = payload.get("product")
    if isinstance(product, dict):
        return str(product.get("name") or product.get("id") or "").strip()
    if isinstance(product, str):
        return product
    return ""


def _order_id(payload: dict) -> str:
    order = payload.get("order")
    if isinstance(order, dict):
        return str(order.get("id") or "")
    return str(order or "")


def route_checkout(payload: dict) -> bool:
    """Add the buyer to the PayGlue blog, if they asked to be added.

    Returns True only when a member was actually created. Never raises into the
    webhook: a newsletter subscription failing must not make Creem retry a
    checkout we already processed for billing.
    """
    # Every rejection is logged. A silent False here is indistinguishable from
    # "it worked but Ghost was quiet", and that ambiguity costs more to debug
    # than these lines cost to write.
    routing = NewsletterRouting.objects.first()
    if routing is None:
        logger.info("Newsletter routing skipped: not configured")
        return False
    if not routing.enabled:
        logger.info("Newsletter routing skipped: disabled")
        return False

    store_id = store_id_of(payload)
    if routing.creem_store_id and store_id and store_id != routing.creem_store_id:
        # Most likely cause of a confusing sandbox test: the test store has its
        # own id. The payload's id is logged so it can be compared, or pasted
        # into the config, without guessing.
        logger.info(
            "Newsletter routing skipped: store %s does not match configured %s",
            store_id,
            routing.creem_store_id,
        )
        return False
    if routing.creem_store_id and not store_id:
        logger.info(
            "Newsletter routing: no store id in payload, store filter not applied"
        )

    if not opted_in(payload, routing.optin_field_key):
        logger.info(
            "Newsletter routing skipped: no ticked '%s' in %s",
            routing.optin_field_key,
            sorted(payload.keys()),
        )
        return False

    email = _email_of(payload)
    if not email:
        logger.warning("Newsletter opt-in with no email in payload; skipping")
        return False

    try:
        _create_ghost_member(routing, email, payload)
    except Exception:
        logger.exception("Newsletter opt-in for %s could not be routed to Ghost", email)
        return False
    return True


def _create_ghost_member(routing: NewsletterRouting, email: str, payload: dict | None = None) -> None:
    """Reuse the tenant Ghost adapter rather than reimplementing its Admin JWT.

    A second copy of that signing code is a second thing to get wrong, and the
    adapter is already exercised by every customer's own sync.
    """
    from payglue_backend.webhooks.adapters.ghost import GhostCmsAdapter, UrllibHttpApiClient
    from payglue_backend.webhooks.credentials import FernetCipher

    if not routing.ghost_admin_api_key_enc:
        raise NewsletterRoutingError("No Ghost admin API key configured.")
    # decrypt() raises on anything that is not a valid token, so the empty
    # check above has to come first rather than relying on a falsy result.
    api_key = FernetCipher().decrypt(routing.ghost_admin_api_key_enc)

    # The adapter expects a tenant credential provider. There is no tenant here
    # -- this is PayGlue's own blog -- so it gets the one set it needs, shared
    # with the health check so both authenticate identically.
    adapter = GhostCmsAdapter(
        http_client=UrllibHttpApiClient(),
        credential_provider=_static_provider(routing, api_key),
    )
    adapter.apply_entitlement(
        customer=CanonicalCustomer(email=email),
        instruction=EntitlementInstruction(
            entitlement_key="newsletter",
            action="grant",
            metadata={
                "ghost_subscribed": True,
                "ghost_email_types": [routing.ghost_email_type]
                if routing.ghost_email_type
                else [],
                "ghost_labels": routing.labels,
                # The adapter writes these into the member note. entitlement_key
                # stays "newsletter" so the product:newsletter label keeps
                # identifying how they arrived; the note carries what they
                # actually bought, which is the part a human reads.
                "_provider": "creem",
                "_product_id": _product_label(payload or {}) or "newsletter opt-in",
                "_event_id": _order_id(payload or {}),
            },
        ),
        tenant_ctx=TenantContext(tenant_slug="payglue-blog"),
    )


def check_connection(routing: "NewsletterRouting") -> tuple[bool, str]:
    """Ask Ghost whether these credentials actually work.

    Reads the site endpoint rather than writing anything: a health check that
    creates a member to prove it can create members is not a health check.
    """
    from payglue_backend.webhooks.adapters.ghost import GhostCmsAdapter, UrllibHttpApiClient
    from payglue_backend.webhooks.credentials import FernetCipher

    if not routing.ghost_api_base_url:
        return False, "No Ghost URL configured."
    if not routing.ghost_admin_api_key_enc:
        return False, "No admin API key stored."

    try:
        api_key = FernetCipher().decrypt(routing.ghost_admin_api_key_enc)
    except ValueError:
        return False, "Stored key could not be decrypted (wrong CREDENTIAL_ENCRYPTION_KEY?)."

    try:
        adapter = GhostCmsAdapter(
            http_client=UrllibHttpApiClient(),
            credential_provider=_static_provider(routing, api_key),
        )
        token = adapter._build_admin_jwt(api_key)
    except Exception as exc:
        return False, f"Could not build an admin token: {exc}"

    base = routing.ghost_api_base_url.rstrip("/")
    try:
        response = UrllibHttpApiClient().get(
            f"{base}/ghost/api/admin/site/",
            headers={
                "Authorization": f"Ghost {token}",
                "Accept-Version": "v5.0",
            },
        )
    except Exception as exc:
        return False, f"Could not reach {base}: {exc}"

    if 200 <= response.status_code < 300:
        return True, f"Reached {base} and authenticated."
    return False, f"{base} answered {response.status_code}."


def _static_provider(routing: "NewsletterRouting", api_key: str):
    class _StaticCredentials:
        def get_credentials(self, tenant_ctx, provider_key):
            del tenant_ctx, provider_key
            return {
                "api_base_url": routing.ghost_api_base_url,
                "admin_api_key": api_key,
            }

    return _StaticCredentials()

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-202: one-click connection verification.

Simulate a mapping's own canonical event against a creator-supplied test
email and run it through the *real* resolver + CMS (Ghost) adapter, so the
creator can confirm the whole chain (Ghost credentials, mapping, delivery)
works without waiting for a real purchase.

Deliberately out-of-band from the live ingestion path:

- No signature verification and no provider webhook is involved -- we build
  the CanonicalPaymentEvent directly from the mapping the creator picked.
- Nothing is written to WebhookInboundEvent and nothing touches the
  idempotency chain (WebhookEventRecord), so a test never pollutes the event
  log, never blocks a later real event with the same id, and can be run any
  number of times.
- The entitlement is applied for real (the test email actually becomes the
  mapped Ghost member) -- that *is* the verification. Use an address you
  control; there is no auto-cleanup.
"""
from django.utils import timezone

from payglue_backend.core.errors import CmsApplyEntitlementError, MissingCredentialsError
from payglue_backend.core.models import (
    CanonicalCustomer,
    CanonicalLineItem,
    CanonicalPaymentEvent,
    TenantContext,
)
from payglue_backend.webhooks import wiring
from payglue_backend.webhooks.models import ProductMapping
from payglue_backend.webhooks.resolver import DbProductMappingResolver


def run_mapping_test(mapping: ProductMapping, test_email: str) -> dict:
    """Fire a synthetic event for `mapping` at `test_email` through the real
    resolve + apply pipeline. Returns a JSON-serialisable result dict:

        {"ok": bool, "applied": int,
         "entitlements": [{"entitlement_key", "action"}], "error": str | None}

    Never raises for the expected failure modes (no mapping resolved, missing
    or invalid Ghost credentials, Ghost API error) -- those come back as
    ok=False with a human-readable `error` so the UI can show the concrete
    problem.
    """
    tenant_ctx = TenantContext(tenant_slug=mapping.tenant_slug)
    now = timezone.now()
    event = CanonicalPaymentEvent(
        provider=mapping.payment_provider,
        # Clearly-synthetic id; it is never persisted to the idempotency chain.
        provider_event_id=f"test-{mapping.id}-{int(now.timestamp())}",
        event_type=mapping.event_type,
        occurred_at=now,
        customer=CanonicalCustomer(email=test_email),
        line_items=(
            CanonicalLineItem(
                external_product_id=mapping.external_product_id,
                quantity=1,
                amount_minor=0,
                currency="EUR",
            ),
        ),
        status="test",
    )

    instructions = list(DbProductMappingResolver().resolve(event, tenant_ctx))
    if not instructions:
        return {
            "ok": False,
            "applied": 0,
            "entitlements": [],
            "error": (
                "No active mapping resolved for this product and trigger. "
                "Check that the mapping is active and that its product ID and "
                "trigger match."
            ),
        }

    cms_adapter = wiring.get_cms_adapter(wiring.get_tenant_cms_provider_key(mapping.tenant_slug))
    applied: list[dict] = []
    try:
        for instruction in instructions:
            cms_adapter.apply_entitlement(event.customer, instruction, tenant_ctx)
            applied.append(
                {"entitlement_key": instruction.entitlement_key, "action": instruction.action}
            )
    except (CmsApplyEntitlementError, MissingCredentialsError) as exc:
        return {
            "ok": False,
            "applied": len(applied),
            "entitlements": applied,
            "error": str(exc),
        }

    return {"ok": True, "applied": len(applied), "entitlements": applied, "error": None}

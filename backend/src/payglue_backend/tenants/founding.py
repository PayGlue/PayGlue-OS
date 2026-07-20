# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Founding-member spot counting.

The ladder lives in Supabase's `pricing_tiers`, which both marketing pages
read live. Until now nothing ever wrote to it: `spots_sold` sat at 0 through
the first real sale, and `active` never moved, so the price would not have
risen for buyer eleven either.

This closes that. One rule, and it matters more than the counter: **nothing
in here may ever break a checkout.** The buyer has already paid by the time we
run, and the webhook's job -- granting them access -- is done before we are
called. A miscounted spot is an annoyance somebody can fix with one UPDATE.
A webhook that 500s because a counter failed costs a customer their account.
So every entry point swallows its exceptions and logs.
"""
from __future__ import annotations

import json
import logging
from urllib import error, request

from django.conf import settings
from django.db import IntegrityError, transaction

from payglue_backend.authn.lifecycle_emails import _send_branded
from payglue_backend.tenants.models import FoundingSale

logger = logging.getLogger(__name__)

_TIMEOUT = 8


def _order_id(checkout: dict) -> str:
    """Creem's stable id for this purchase.

    Prefer the order, fall back to the checkout itself. One of the two is
    always present, and either is stable across retries, which is all the
    idempotency key has to be.
    """
    order = checkout.get("order")
    if isinstance(order, dict) and order.get("id"):
        return str(order["id"])
    if isinstance(order, str) and order:
        return order
    return str(checkout.get("id") or "")


def _product_id(checkout: dict) -> str:
    product = checkout.get("product")
    if isinstance(product, dict):
        return str(product.get("id") or "")
    return str(product or "")


def _claim_spot(product_id: str) -> dict | None:
    """Ask Postgres to claim one spot, atomically.

    The increment and the ladder advance happen inside `claim_founding_spot`
    under a row lock, so two purchases landing together cannot take the same
    spot. Returns None when the product is not a founding tier.
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        logger.warning("founding: Supabase is not configured, not counting the sale")
        return None

    payload = json.dumps({"p_product_id": product_id}).encode()
    req = request.Request(
        url=f"{settings.SUPABASE_URL}/rest/v1/rpc/claim_founding_spot",
        data=payload,
        headers={
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=_TIMEOUT) as resp:
            rows = json.loads(resp.read().decode())
    except error.HTTPError as exc:
        detail = exc.read().decode()[:500] if exc.fp else ""
        logger.warning("founding: claim failed: HTTP %s: %s", exc.code, detail)
        return None
    except (error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("founding: claim failed: %s", exc)
        return None

    # No rows means the product belongs to no tier: a dashboard upgrade or any
    # other non-founding purchase. Not an error, just not ours.
    if not rows:
        return None
    return rows[0]


def record_sale(checkout: dict, email: str = "") -> None:
    """Count a completed checkout against the founding ladder.

    Best effort by construction. Callers must not depend on it having worked,
    and must not let it raise.
    """
    order_id = _order_id(checkout)
    product_id = _product_id(checkout)
    if not order_id or not product_id:
        logger.warning(
            "founding: checkout has no usable order/product id, not counting"
        )
        return

    # Claim the local row first. The unique constraint is what makes a Creem
    # retry harmless: the second delivery loses the race to insert and returns
    # before touching the counter.
    # The savepoint is not decoration. An IntegrityError raised inside an
    # enclosing transaction poisons it: every later query, including the
    # commit at the end of the request, fails with TransactionManagementError.
    # On the retried webhook that duplicate is the *expected* path, so without
    # this the second delivery would 500 -- the exact failure this module
    # promises never to cause. Caught by CI, not by review.
    try:
        with transaction.atomic():
            sale = FoundingSale.objects.create(
                order_id=order_id, product_id=product_id, email=email
            )
    except IntegrityError:
        logger.info("founding: order %s was already counted, skipping", order_id)
        return

    claimed = _claim_spot(product_id)
    if claimed is None:
        # Either not a founding product, or Supabase was unreachable. The row
        # stays either way: with tier=None it records that we saw this order
        # and decided not to count it.
        return

    sale.tier = claimed.get("claimed_tier")
    sale.price_cents = claimed.get("price_cents")
    sale.tier_was_active = claimed.get("was_active")
    sale.save(update_fields=["tier", "price_cents", "tier_was_active"])

    # PG-211: the ladder advances on the website, but the old Creem checkout
    # link keeps working, and Creem enforces no quantity limit. A purchase into
    # a tier we already closed is therefore possible and invisible without this.
    # Reported rather than prevented: locking a shared link down would cost more
    # than the handful of accounts it could ever affect.
    if claimed.get("was_active") is False:
        _report_late_purchase(sale)

    if claimed.get("sold_out"):
        logger.info(
            "founding: tier %s is sold out (%s/%s), ladder advanced",
            claimed.get("claimed_tier"),
            claimed.get("sold"),
            claimed.get("total"),
        )
    else:
        logger.info(
            "founding: tier %s now at %s/%s",
            claimed.get("claimed_tier"),
            claimed.get("sold"),
            claimed.get("total"),
        )


def record_sale_safely(checkout: dict, email: str = "") -> None:
    """The only entry point a webhook should use.

    A counter must never be the reason a paid customer's webhook fails.
    """
    try:
        record_sale(checkout, email)
    except Exception:  # noqa: BLE001 - deliberately total, see module docstring
        logger.exception("founding: counting a sale failed, checkout is unaffected")


def _report_late_purchase(sale: FoundingSale) -> None:
    """Tell us when somebody bought into a tier that had already closed.

    Their money is taken and their spot counted either way; what happens next
    (honour it, or refund and move them to the current tier) is a judgement
    call, so this only makes the case visible.
    """
    try:
        _send_branded(
            f"Founding: late purchase into tier {sale.tier}",
            f"{sale.email} bought order {sale.order_id} against product "
            f"{sale.product_id}, which belongs to tier {sale.tier}.\n\n"
            "That tier was already sold out when the purchase landed, so this "
            "came through an old checkout link. The spot was counted and capped "
            "at the tier total.\n\n"
            "Decide whether to honour the price or refund and move them to the "
            "tier that is currently on sale.",
            [settings.INTERNAL_ADMIN_EMAIL],
        )
    except Exception:  # noqa: BLE001 - a paid checkout must not fail over a notice
        logger.exception("founding: could not report late purchase %s", sale.pk)

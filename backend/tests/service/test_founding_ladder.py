# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Counting founding-member spots against the Supabase ladder.

Written against a live product. The first real sale (9 EUR, tier 1) went
through with the counter still on zero, which is what surfaced the whole gap:
nothing had ever written to `pricing_tiers`, so the ladder would not have
advanced for buyer eleven either -- they would have paid 9 EUR instead of 19.

The tests that matter most here are the ones proving this code cannot hurt a
checkout. The buyer has already paid by the time any of it runs.
"""
from unittest import mock

import pytest
from django.db import IntegrityError

from payglue_backend.tenants import founding
from payglue_backend.tenants.models import FoundingSale

pytestmark = pytest.mark.django_db

TIER1_PRODUCT = "prod_387Ltfpg7RIhb30pPexk7d"


def _checkout(**overrides) -> dict:
    checkout = {
        "id": "ch_abc",
        "order": {"id": "ORD-19F802B22932D892"},
        "product": {"id": TIER1_PRODUCT},
    }
    checkout.update(overrides)
    return checkout


def _claimed(tier=1, total=10, sold=1, sold_out=False) -> dict:
    return {"claimed_tier": tier, "total": total, "sold": sold, "sold_out": sold_out}


# --- the counting itself --------------------------------------------------


def test_a_founding_sale_claims_a_spot() -> None:
    with mock.patch.object(founding, "_claim_spot", return_value=_claimed()) as claim:
        founding.record_sale(_checkout(), "buyer@example.com")

    claim.assert_called_once_with(TIER1_PRODUCT)
    sale = FoundingSale.objects.get()
    assert sale.order_id == "ORD-19F802B22932D892"
    assert sale.tier == 1
    assert sale.email == "buyer@example.com"


def test_a_retried_webhook_does_not_burn_a_second_spot() -> None:
    """Creem retries deliveries. Without the unique order id, a retry would
    take another spot and walk the price ladder forward early."""
    with mock.patch.object(founding, "_claim_spot", return_value=_claimed()) as claim:
        founding.record_sale(_checkout(), "buyer@example.com")
        founding.record_sale(_checkout(), "buyer@example.com")

    assert claim.call_count == 1
    assert FoundingSale.objects.count() == 1


def test_a_non_founding_product_is_recorded_but_not_counted() -> None:
    """A dashboard upgrade matches no tier. The row still lands, so we can
    tell "we ignored this one" apart from "we never saw it"."""
    with mock.patch.object(founding, "_claim_spot", return_value=None):
        founding.record_sale(_checkout(product={"id": "prod_some_plan"}), "x@example.com")

    sale = FoundingSale.objects.get()
    assert sale.tier is None


def test_the_checkout_id_stands_in_for_a_missing_order() -> None:
    with mock.patch.object(founding, "_claim_spot", return_value=_claimed()):
        founding.record_sale(_checkout(order=None), "buyer@example.com")

    assert FoundingSale.objects.get().order_id == "ch_abc"


def test_a_payload_without_any_id_is_skipped_rather_than_guessed() -> None:
    with mock.patch.object(founding, "_claim_spot") as claim:
        founding.record_sale({"product": {"id": TIER1_PRODUCT}}, "buyer@example.com")

    claim.assert_not_called()
    assert FoundingSale.objects.count() == 0


def test_a_product_as_a_bare_string_is_read_too() -> None:
    """Creem expands `product` inconsistently between events."""
    with mock.patch.object(founding, "_claim_spot", return_value=_claimed()) as claim:
        founding.record_sale(_checkout(product=TIER1_PRODUCT), "buyer@example.com")

    claim.assert_called_once_with(TIER1_PRODUCT)


# --- nothing here may break a checkout ------------------------------------


def test_supabase_being_down_does_not_raise() -> None:
    with mock.patch.object(founding, "_claim_spot", side_effect=RuntimeError("supabase down")):
        founding.record_sale_safely(_checkout(), "buyer@example.com")


def test_a_database_failure_does_not_raise() -> None:
    """The customer has already paid. A 500 out of this webhook makes Creem
    retry forever and can cost them their account."""
    with mock.patch.object(
        FoundingSale.objects, "create", side_effect=IntegrityError("boom")
    ):
        founding.record_sale_safely(_checkout(), "buyer@example.com")


def test_a_completely_broken_payload_does_not_raise() -> None:
    founding.record_sale_safely({"product": object()}, "buyer@example.com")  # type: ignore[dict-item]


def test_an_unreachable_supabase_leaves_the_sale_recorded() -> None:
    """We still know the order happened, so the counter can be corrected by
    hand without hunting through Creem."""
    with mock.patch.object(founding, "_claim_spot", return_value=None):
        founding.record_sale(_checkout(), "buyer@example.com")

    assert FoundingSale.objects.filter(order_id="ORD-19F802B22932D892").exists()


# --- the RPC boundary -----------------------------------------------------


def test_no_supabase_config_means_no_call(settings) -> None:
    settings.SUPABASE_URL = ""
    settings.SUPABASE_SERVICE_ROLE_KEY = ""
    assert founding._claim_spot(TIER1_PRODUCT) is None


def test_an_empty_result_set_means_not_a_founding_product(settings) -> None:
    settings.SUPABASE_URL = "https://example.supabase.co"
    settings.SUPABASE_SERVICE_ROLE_KEY = "service-key"

    with mock.patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = b"[]"
        assert founding._claim_spot("prod_not_a_tier") is None


def test_the_claimed_row_is_returned(settings) -> None:
    settings.SUPABASE_URL = "https://example.supabase.co"
    settings.SUPABASE_SERVICE_ROLE_KEY = "service-key"

    body = b'[{"claimed_tier":1,"total":10,"sold":2,"sold_out":false}]'
    with mock.patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = body
        assert founding._claim_spot(TIER1_PRODUCT) == {
            "claimed_tier": 1,
            "total": 10,
            "sold": 2,
            "sold_out": False,
        }


def test_a_duplicate_leaves_the_transaction_usable() -> None:
    """The regression CI caught. An IntegrityError inside an enclosing
    transaction poisons it, so the retried delivery -- where a duplicate is
    the expected outcome -- would have 500'd on the request's own commit.
    Querying after the duplicate proves the savepoint contained it."""
    with mock.patch.object(founding, "_claim_spot", return_value=_claimed()):
        founding.record_sale(_checkout(), "buyer@example.com")
        founding.record_sale(_checkout(), "buyer@example.com")

    assert FoundingSale.objects.count() == 1


# --- PG-210: the locked rate is captured, not looked up --------------------


def test_the_rate_is_stored_with_the_sale() -> None:
    """Copied at purchase rather than derived from the ladder later. If the
    price were looked up on demand, editing a tier would retroactively change
    what an existing member was promised for life."""
    claimed = {**_claimed(), "price_cents": 900, "was_active": True}
    with mock.patch.object(founding, "_claim_spot", return_value=claimed):
        founding.record_sale(_checkout(), "buyer@example.com")

    sale = FoundingSale.objects.get()
    assert sale.price_cents == 900
    assert sale.tier_was_active is True


# --- PG-211: buying through a link into a closed tier ----------------------


def test_a_purchase_into_a_closed_tier_is_reported(settings) -> None:
    from django.core import mail

    # Internal notices have no default recipient since PG-239, so the address
    # has to be configured for one to go anywhere at all.
    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    claimed = {**_claimed(tier=1), "price_cents": 900, "was_active": False}
    with mock.patch.object(founding, "_claim_spot", return_value=claimed):
        founding.record_sale(_checkout(), "late@example.com")

    subjects = [m.subject for m in mail.outbox]
    assert any("late purchase" in s for s in subjects), subjects
    assert FoundingSale.objects.get().tier_was_active is False


def test_a_normal_purchase_is_not_reported() -> None:
    from django.core import mail

    claimed = {**_claimed(), "price_cents": 900, "was_active": True}
    with mock.patch.object(founding, "_claim_spot", return_value=claimed):
        founding.record_sale(_checkout(), "buyer@example.com")

    assert not [m for m in mail.outbox if "late purchase" in m.subject]


def test_a_failing_report_does_not_lose_the_sale() -> None:
    """Same rule as everywhere else in this module: the buyer has paid, so a
    notification problem must not surface as a webhook failure."""
    claimed = {**_claimed(), "price_cents": 900, "was_active": False}
    with mock.patch.object(founding, "_claim_spot", return_value=claimed), \
         mock.patch.object(founding, "_send_branded", side_effect=RuntimeError("resend down")):
        founding.record_sale_safely(_checkout(), "late@example.com")

    assert FoundingSale.objects.count() == 1

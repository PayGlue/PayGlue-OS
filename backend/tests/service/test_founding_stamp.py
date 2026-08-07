# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-210: stamping the founding batch and rate onto a new account.

Signup is the one moment the purchase email and the account are both in hand.
Matching them up later means matching on email months after the fact, which
breaks the first time somebody checks out with one address and registers with
another.
"""
import pytest

from payglue_backend.tenants.models import BillingAccount, FoundingSale, Plan, UserProfile
from payglue_backend.tenants.serializers import TenantCreateSerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile() -> UserProfile:
    return UserProfile.objects.create(firebase_uid="uid-1", email="buyer@example.com")


def _create_tenant(profile: UserProfile, slug: str = "acme"):
    serializer = TenantCreateSerializer(
        data={"slug": slug, "name": "Acme"}, context={"user_profile": profile}
    )
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def _sale(email: str, tier: int = 2, price_cents: int = 1400) -> FoundingSale:
    return FoundingSale.objects.create(
        order_id=f"ORD-{email}-{tier}",
        product_id="prod_x",
        email=email,
        tier=tier,
        price_cents=price_cents,
    )


def test_a_founding_buyer_gets_stamped(profile: UserProfile) -> None:
    _sale("buyer@example.com")
    _create_tenant(profile)

    account = BillingAccount.objects.get(owner=profile)
    assert account.founding_tier == 2
    assert account.founding_price_cents == 1400


def test_the_email_match_ignores_case(profile: UserProfile) -> None:
    """Creem echoes back whatever casing the buyer typed."""
    _sale("BUYER@Example.com")
    _create_tenant(profile)

    assert BillingAccount.objects.get(owner=profile).founding_tier == 2


def test_somebody_who_never_bought_is_left_blank(profile: UserProfile) -> None:
    _create_tenant(profile)

    account = BillingAccount.objects.get(owner=profile)
    assert account.founding_tier is None
    assert account.founding_price_cents is None


def test_a_non_founding_sale_does_not_stamp(profile: UserProfile) -> None:
    """A dashboard upgrade lands in FoundingSale with tier=None, recording that
    we saw the order and decided not to count it. It is not a founding spot."""
    FoundingSale.objects.create(
        order_id="ORD-upgrade", product_id="prod_plan", email="buyer@example.com"
    )
    _create_tenant(profile)

    assert BillingAccount.objects.get(owner=profile).founding_tier is None


def test_the_earliest_purchase_wins(profile: UserProfile) -> None:
    """Somebody could conceivably buy twice. The first spot is the one they
    were promised, and it is always the cheaper of the two."""
    _sale("buyer@example.com", tier=1, price_cents=900)
    _sale("buyer@example.com", tier=3, price_cents=1900)
    _create_tenant(profile)

    assert BillingAccount.objects.get(owner=profile).founding_price_cents == 900


def test_a_second_tenant_does_not_restamp(profile: UserProfile) -> None:
    """The stamp lives on the BillingAccount, which is created once. Creating
    another publication must not re-run the lookup."""
    _sale("buyer@example.com", tier=2, price_cents=1400)
    _create_tenant(profile, slug="acme")

    account = BillingAccount.objects.get(owner=profile)
    account.founding_price_cents = 111
    account.save(update_fields=["founding_price_cents"])

    _create_tenant(profile, slug="acme-two")
    account.refresh_from_db()
    assert account.founding_price_cents == 111

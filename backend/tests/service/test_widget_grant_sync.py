# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Saving a widget is what creates the rule for its product (PG-254).

These go through the real endpoints rather than calling `mapping_sync` directly,
because the thing that used to be broken was not the writing of a rule but who
did it: three editors each made a second call from the browser, decided between
create and update by searching a possibly stale list, and invented their own
`entitlement_key`. The case that motivated the change is
`test_a_button_and_a_tier_on_one_product_share_one_rule` below.
"""

import json
from dataclasses import dataclass

import pytest
from django.test import Client

from payglue_backend.tenants.models import Tenant, TenantMembership, UserProfile
from payglue_backend.webhooks.models import ProductMapping

pytestmark = pytest.mark.django_db

PRODUCT = "prod_shared"


@dataclass(frozen=True)
class _StubClaims:
    firebase_uid: str
    email: str


class _StubVerifier:
    def __init__(self, claims: _StubClaims) -> None:
        self._claims = claims

    def verify(self, token: str):
        del token
        return self._claims


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    tenant = Tenant.objects.create(slug="tenant-a", schema_name="tenant_a")
    profile = UserProfile.objects.create(firebase_uid="uid-owner", email="owner@example.com")
    TenantMembership.objects.create(
        tenant=tenant, user_profile=profile, role=TenantMembership.Role.OWNER
    )
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(
            _StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)
        ),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


def _post(client: Client, path: str, payload: dict, headers: dict):
    return client.post(
        f"/t/tenant-a/api/v1/{path}",
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )


def _button_payload(**grant) -> dict:
    return {
        "name": "Go Pro",
        "label": "Buy now",
        "product_provider": "polar",
        "product_id": PRODUCT,
        "grant": {"entitlement_key": "pro", "metadata": {"ghost_subscribed": True}, **grant},
    }


def _table_payload(**grant) -> dict:
    return {
        "name": "Homepage",
        "tiers": [
            {"name": "Free", "cta_type": "free_signup"},
            {
                "name": "Pro",
                "product_provider": "polar",
                "product_id": PRODUCT,
                "grant": {"metadata": {"ghost_subscribed": False}, **grant},
            },
        ],
    }


def test_saving_a_button_with_a_product_creates_its_rule(owner) -> None:
    """The browser used to make a second call for this, which could fail on its
    own and leave a button that takes money and grants nothing."""
    response = _post(Client(), "buttons", _button_payload(), owner)

    assert response.status_code == 201
    rule = ProductMapping.objects.get()
    assert rule.external_product_id == PRODUCT
    assert rule.payment_provider == "polar"
    assert rule.action == "grant"
    assert rule.entitlement_key == "pro"
    assert rule.metadata["ghost_subscribed"] is True


def test_a_button_and_a_tier_on_one_product_share_one_rule(owner) -> None:
    """The case from the ticket.

    Before, the button wrote a rule keyed `button` and the tier wrote one keyed
    `product-<id>`. A purchase applied both, in id order, so whichever came
    second silently decided the member's newsletter flag. Now the tier updates
    the button's rule instead of adding a competing one.
    """
    client = Client()
    _post(client, "buttons", _button_payload(), owner)

    _post(client, "pricing-tables", _table_payload(), owner)

    rule = ProductMapping.objects.get()
    assert rule.metadata["ghost_subscribed"] is False


def test_the_rule_keeps_the_name_it_was_created_with(owner) -> None:
    """`entitlement_key` reaches Ghost as `product:<key>` and is already written
    onto members. A second widget saving the same product must not rename it."""
    client = Client()
    _post(client, "buttons", _button_payload(), owner)

    _post(client, "pricing-tables", _table_payload(entitlement_key="something-else"), owner)

    assert ProductMapping.objects.get().entitlement_key == "pro"


def test_saving_a_widget_without_a_product_creates_no_rule(owner) -> None:
    """A button can be saved before a product has been picked, and a free tier
    never has one. Neither is an error and neither has anything to map."""
    client = Client()

    _post(client, "buttons", {"name": "Just a link", "target_url": "https://example.com"}, owner)
    _post(client, "pricing-tables", {"name": "Free only", "tiers": [{"name": "Free"}]}, owner)

    assert ProductMapping.objects.count() == 0


def test_two_tiers_on_the_same_product_in_one_table_are_not_an_error(owner) -> None:
    """A monthly and a yearly column can point at the same product. Saving used
    to run into the unique constraint and return a 400 for the second one."""
    payload = {
        "name": "Homepage",
        "tiers": [
            {"name": "Monthly", "product_provider": "polar", "product_id": PRODUCT},
            {"name": "Yearly", "product_provider": "polar", "product_id": PRODUCT},
        ],
    }

    response = _post(Client(), "pricing-tables", payload, owner)

    assert response.status_code == 201
    assert ProductMapping.objects.count() == 1


def test_a_paywall_on_the_same_product_joins_the_same_rule(owner) -> None:
    """The paywall was the third editor with its own key, `paywall`."""
    client = Client()
    _post(client, "buttons", _button_payload(), owner)

    response = _post(
        client,
        "paywalls",
        {
            "name": "Members only",
            "product_provider": "polar",
            "product_id": PRODUCT,
            "grant": {"metadata": {"ghost_labels": ["vip"]}},
        },
        owner,
    )

    assert response.status_code == 201
    rule = ProductMapping.objects.get()
    assert rule.metadata["ghost_labels"] == ["vip"]
    assert rule.entitlement_key == "pro"


def test_pointing_a_button_at_a_different_product_leaves_the_old_rule_alone(owner) -> None:
    """Removing a product from a widget does not un-sell it. A checkout link
    already out in the world keeps working, and a purchase through it still has
    to grant what it promised."""
    client = Client()
    created = _post(client, "buttons", _button_payload(), owner)
    button_id = created.json()["id"]

    client.patch(
        f"/t/tenant-a/api/v1/buttons/{button_id}",
        data=json.dumps({"product_id": "prod_other", "grant": {"entitlement_key": "other"}}),
        content_type="application/json",
        **owner,
    )

    assert set(ProductMapping.objects.values_list("external_product_id", flat=True)) == {
        PRODUCT,
        "prod_other",
    }


def test_the_mapping_list_names_every_widget_offering_the_product(owner) -> None:
    """What Andre saw on staging: a product on a buy button and a pricing tier
    showed only the tier, because "used in" came from the rule's own metadata
    and the tier had saved last. With one rule between them that is not merely
    incomplete, it is wrong, so the server works it out from the widgets."""
    client = Client()
    _post(client, "buttons", _button_payload(), owner)
    _post(client, "pricing-tables", _table_payload(), owner)

    rows = client.get("/t/tenant-a/api/v1/mappings", **owner).json()

    assert len(rows) == 1
    assert rows[0]["used_in"] == [
        "Buy Button: Go Pro",
        "Pricing Table: Homepage · Pro",
    ]


def test_a_product_no_widget_offers_says_so_rather_than_naming_a_stale_one(owner) -> None:
    """A rule outlives the widget that created it, on purpose: a checkout link
    already out in the world still has to grant what it promised."""
    client = Client()
    created = _post(client, "buttons", _button_payload(), owner)
    client.delete(
        f"/t/tenant-a/api/v1/buttons/{created.json()['id']}", **owner
    )

    rows = client.get("/t/tenant-a/api/v1/mappings", **owner).json()

    assert len(rows) == 1
    assert rows[0]["used_in"] == []

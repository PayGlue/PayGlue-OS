# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Creem newsletter opt-in to the PayGlue blog.

The payload assertions here are built from the real sandbox response André
captured, not from the docs. The two things that differ between the two are
exactly the two that would have shipped broken.
"""
from unittest import mock

import pytest

from payglue_backend.authn import newsletter
from payglue_backend.tenants.models import NewsletterRouting

pytestmark = pytest.mark.django_db

STORE = "sto_3MX9ng1a4C6U5PVWJVbuQm"

# Copied from the live sandbox payload. Note customFields (camelCase) and the
# empty checkbox label -- the consent wording only exists on the product.
SANDBOX_FIELD = {
    "key": "newsletteroptin",
    "type": "checkbox",
    "label": "Newsletter-Opt-in",
    "checkbox": {"label": "", "value": True},
    "optional": True,
}


def _routing(**overrides) -> NewsletterRouting:
    defaults = {
        "enabled": True,
        "ghost_api_base_url": "https://blog.example.com",
        "ghost_admin_api_key_enc": "irrelevant-for-these-tests",
        "creem_store_id": STORE,
    }
    defaults.update(overrides)
    return NewsletterRouting.objects.create(**defaults)


def _payload(**overrides) -> dict:
    payload = {
        "store_id": STORE,
        "customer": {"email": "buyer@example.com"},
        "customFields": [SANDBOX_FIELD],
    }
    payload.update(overrides)
    return payload


# --- reading the checkbox -------------------------------------------------


def test_camelcase_is_read() -> None:
    """The checkout payload spells it customFields."""
    assert newsletter.opted_in(_payload()) is True


def test_snake_case_is_read_too() -> None:
    """The products API spells the same thing custom_fields. A reader that
    knows one spelling finds nothing and raises nothing."""
    assert newsletter.opted_in({"custom_fields": [SANDBOX_FIELD]}) is True


def test_an_unticked_box_is_a_no() -> None:
    field = {**SANDBOX_FIELD, "checkbox": {"label": "", "value": False}}
    assert newsletter.opted_in({"customFields": [field]}) is False


def test_a_missing_field_is_a_no() -> None:
    """Consent that has to be inferred is not consent."""
    assert newsletter.opted_in({"customFields": []}) is False
    assert newsletter.opted_in({}) is False


def test_a_missing_value_is_a_no() -> None:
    field = {**SANDBOX_FIELD, "checkbox": {"label": ""}}
    assert newsletter.opted_in({"customFields": [field]}) is False


def test_a_different_field_key_is_ignored() -> None:
    field = {**SANDBOX_FIELD, "key": "somethingelse"}
    assert newsletter.opted_in({"customFields": [field]}) is False


# --- routing --------------------------------------------------------------


def test_an_opt_in_creates_a_member() -> None:
    _routing()
    with mock.patch.object(newsletter, "_create_ghost_member") as create:
        assert newsletter.route_checkout(_payload()) is True
    create.assert_called_once()
    assert create.call_args[0][1] == "buyer@example.com"


def test_no_opt_in_creates_nothing() -> None:
    _routing()
    field = {**SANDBOX_FIELD, "checkbox": {"value": False}}
    with mock.patch.object(newsletter, "_create_ghost_member") as create:
        assert newsletter.route_checkout(_payload(customFields=[field])) is False
    create.assert_not_called()


def test_a_different_store_is_ignored() -> None:
    """Only this store's checkouts feed the blog; other Creem products of
    André's are not PayGlue customers."""
    _routing()
    with mock.patch.object(newsletter, "_create_ghost_member") as create:
        assert newsletter.route_checkout(_payload(store_id="sto_somethingelse")) is False
    create.assert_not_called()


def test_disabled_routing_does_nothing() -> None:
    _routing(enabled=False)
    with mock.patch.object(newsletter, "_create_ghost_member") as create:
        assert newsletter.route_checkout(_payload()) is False
    create.assert_not_called()


def test_no_configuration_at_all_does_nothing() -> None:
    with mock.patch.object(newsletter, "_create_ghost_member") as create:
        assert newsletter.route_checkout(_payload()) is False
    create.assert_not_called()


def test_a_ghost_failure_never_escapes() -> None:
    """The billing side of this checkout already succeeded. A blog hiccup must
    not make Creem retry the whole thing."""
    _routing()
    with mock.patch.object(newsletter, "_create_ghost_member", side_effect=RuntimeError("ghost down")):
        assert newsletter.route_checkout(_payload()) is False


def test_an_opt_in_without_an_email_is_skipped() -> None:
    _routing()
    with mock.patch.object(newsletter, "_create_ghost_member") as create:
        assert newsletter.route_checkout(_payload(customer={})) is False
    create.assert_not_called()


# --- what Ghost is asked for ---------------------------------------------


def test_ghost_gets_the_double_opt_in_email_and_the_client_label() -> None:
    """subscribe is Ghost's newsletter opt-in mail: somebody who never confirms
    never joins the list, which is the whole point of doing it this way."""
    routing = _routing()
    captured = {}

    class _Adapter:
        def __init__(self, **kwargs):
            pass

        def apply_entitlement(self, customer, instruction, tenant_ctx):
            captured["metadata"] = instruction.metadata
            captured["email"] = customer.email

    with mock.patch("payglue_backend.webhooks.adapters.ghost.GhostCmsAdapter", _Adapter), \
         mock.patch("payglue_backend.webhooks.credentials.FernetCipher.decrypt", return_value="key"):
        newsletter._create_ghost_member(routing, "buyer@example.com")

    assert captured["email"] == "buyer@example.com"
    assert captured["metadata"]["ghost_email_types"] == ["subscribe"]
    assert captured["metadata"]["ghost_labels"] == ["payglue:client"]
    assert captured["metadata"]["ghost_subscribed"] is True


def test_labels_are_split_on_commas() -> None:
    routing = _routing(ghost_labels="payglue:client, vip ,")
    assert routing.labels == ["payglue:client", "vip"]

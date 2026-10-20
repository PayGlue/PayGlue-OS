# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-336: one Ghost member, more than one product.

Ghost has one kind of access per member, and an edit replaces the member's
labels with the list it sends. These tests run the adapter against a small
stand-in for Ghost that keeps that state between calls, so a sequence of
purchases and endings is checked by what the member ends up as, not by the
requests in isolation.
"""

import json

from payglue_backend.core.models import CanonicalCustomer, EntitlementInstruction, TenantContext
from payglue_backend.webhooks.adapters.ghost import GhostCmsAdapter

ADMIN_KEY = "keyid:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class _Credentials:
    def get_credentials(self, tenant_ctx: TenantContext, provider_key: str) -> dict[str, str]:
        return {"api_base_url": "https://ghost.test", "admin_api_key": ADMIN_KEY}


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class FakeGhost:
    """Keeps one member the way Ghost would: labels are replaced by an edit,
    comped:true opens a Complimentary subscription, and comped:false does not
    close it (TryGhost/Ghost#31501), so only the adapter's own cancel does."""

    def __init__(self, *, stripe_connected: bool = True, member: dict | None = None) -> None:
        self.stripe_connected = stripe_connected
        self.member: dict | None = member
        self.member_writes: list[dict] = []

    # -- reads -------------------------------------------------------------
    def get(self, url: str, headers: dict[str, str]) -> _Response:
        if "/settings/" in url:
            value = "acct_1" if self.stripe_connected else ""
            return _Response(200, json.dumps({"settings": [{"key": "stripe_connect_account_id", "value": value}]}))
        if "filter=email" in url:
            return _Response(200, json.dumps({"members": [self.member] if self.member else []}))
        return _Response(200, json.dumps({"members": [self.member or {}]}))

    # -- writes ------------------------------------------------------------
    def post(self, url: str, json_body: dict, headers: dict[str, str]) -> _Response:
        sent = json_body["members"][0]
        self.member = {"id": "m1", "email": sent["email"], "labels": [], "note": "", "comped": False, "subscriptions": []}
        self._apply(sent)
        return _Response(201, json.dumps({"members": [{"id": "m1"}]}))

    def put(self, url: str, json_body: dict, headers: dict[str, str]) -> _Response:
        assert self.member is not None
        if "/subscriptions/" in url:
            sub_id = url.rstrip("/").rsplit("/", 1)[-1]
            for sub in self.member["subscriptions"]:
                if sub["id"] == sub_id:
                    sub["status"] = "canceled"
            self.member["comped"] = False
            return _Response(200, "{}")
        sent = json_body["members"][0]
        self.member_writes.append(sent)
        self._apply(sent)
        return _Response(200, json.dumps({"members": [self.member]}))

    def delete(self, url: str, headers: dict[str, str]) -> _Response:
        return _Response(204)

    def _apply(self, sent: dict) -> None:
        assert self.member is not None
        if "labels" in sent:
            self.member["labels"] = [{"name": label["name"]} for label in sent["labels"]]
        if "note" in sent:
            self.member["note"] = sent["note"]
        if sent.get("comped") and self.stripe_connected:
            self.member["comped"] = True
            if not self.complimentary_active:
                self.member["subscriptions"].append(
                    {"id": f"sub_comp_{len(self.member['subscriptions'])}", "status": "active", "price": {"nickname": "Complimentary", "amount": 0}}
                )

    # -- what a test reads -------------------------------------------------
    @property
    def labels(self) -> list[str]:
        return [label["name"] for label in (self.member or {}).get("labels", [])]

    @property
    def complimentary_active(self) -> bool:
        return any(
            sub["status"] == "active" and sub["price"]["nickname"] == "Complimentary"
            for sub in (self.member or {}).get("subscriptions", [])
        )


def _apply(ghost: FakeGhost, key: str, action: str, day: str = "2026-10-20") -> None:
    adapter = GhostCmsAdapter(http_client=ghost, credential_provider=_Credentials())
    adapter.apply_entitlement(
        CanonicalCustomer(email="reader@example.com"),
        EntitlementInstruction(
            entitlement_key=key,
            action=action,
            quantity=1,
            metadata={"_provider": "creem", "_product_id": key, "_event_id": f"evt_{key}_{action}", "_occurred_at": day},
        ),
        TenantContext(tenant_slug="tenant-a"),
    )


def test_ending_one_product_keeps_the_access_another_product_still_pays_for() -> None:
    """The case from the report: archive A stays valid, subscription B ends."""
    ghost = FakeGhost()

    _apply(ghost, "archive-A", "grant")
    _apply(ghost, "subscription-B", "grant")
    _apply(ghost, "subscription-B", "revoke", day="2026-11-20")

    assert ghost.member["comped"] is True
    assert ghost.complimentary_active
    assert "payglue-active" in ghost.labels
    assert "payglue-ended" not in ghost.labels
    assert "product:archive-a" in ghost.labels
    assert "product:subscription-b" not in ghost.labels
    assert "Ended product:subscription-b: 2026-11-20" in ghost.member["note"]
    assert "comped" not in ghost.member_writes[-1], "a partial ending leaves comped alone"


def test_when_the_last_product_ends_the_access_ends() -> None:
    ghost = FakeGhost()
    _apply(ghost, "archive-A", "grant")
    _apply(ghost, "subscription-B", "grant")
    _apply(ghost, "subscription-B", "revoke", day="2026-11-20")

    _apply(ghost, "archive-A", "revoke", day="2026-12-01")

    assert ghost.member["comped"] is False
    assert not ghost.complimentary_active
    assert "payglue-ended" in ghost.labels
    assert "payglue-active" not in ghost.labels
    # what was bought last stays readable on the ended member
    assert "product:archive-a" in ghost.labels
    note = ghost.member["note"].splitlines()
    assert "Ended product:subscription-b: 2026-11-20 | Event: evt_subscription-B_revoke" in note
    assert note[-1] == "Ended: 2026-12-01 | Event: evt_archive-A_revoke"


def test_a_second_purchase_keeps_the_first_products_label_and_order() -> None:
    ghost = FakeGhost()

    _apply(ghost, "archive-A", "grant")
    _apply(ghost, "subscription-B", "grant")

    assert {"product:archive-a", "product:subscription-b", "payglue-active"} <= set(ghost.labels)
    assert "Order: 2026-10-20 | Event: evt_archive-A_grant" in ghost.member["note"]
    assert "Order: 2026-10-20 | Event: evt_subscription-B_grant" in ghost.member["note"]
    assert len(ghost.member["subscriptions"]) == 1, "one Complimentary subscription, not one per product"


def test_a_purchase_keeps_labels_the_publisher_added_by_hand() -> None:
    ghost = FakeGhost(member={"id": "m1", "email": "reader@example.com", "labels": [{"name": "vip"}, {"name": "podcast-guest"}], "note": "", "comped": False, "subscriptions": []})

    _apply(ghost, "archive-A", "grant")

    assert {"vip", "podcast-guest", "product:archive-a", "payglue-active"} <= set(ghost.labels)


def test_a_purchase_after_an_ending_does_not_revive_the_ended_product() -> None:
    """On an ended member the product label is history. If it survived the
    next purchase, ending that purchase would find it and keep the access."""
    ghost = FakeGhost(
        member={
            "id": "m1",
            "email": "reader@example.com",
            "labels": [{"name": "source:payglue"}, {"name": "product:old-course"}, {"name": "payglue-ended"}, {"name": "payglue-provider:creem"}],
            "note": "",
            "comped": False,
            "subscriptions": [],
        }
    )

    _apply(ghost, "subscription-B", "grant")
    assert "product:old-course" not in ghost.labels
    assert "payglue-ended" not in ghost.labels

    _apply(ghost, "subscription-B", "revoke")
    assert "payglue-ended" in ghost.labels
    assert ghost.member["comped"] is False


def test_an_ending_for_a_product_the_member_never_held_changes_nothing() -> None:
    """Providers that do not name the tier on a cancellation revoke every
    product they can grant. The ones the member never bought must not touch
    the one they did."""
    ghost = FakeGhost()
    _apply(ghost, "archive-A", "grant")
    writes_before = len(ghost.member_writes)

    _apply(ghost, "never-bought", "revoke")

    assert len(ghost.member_writes) == writes_before
    assert ghost.member["comped"] is True
    assert "payglue-active" in ghost.labels


def test_the_old_provider_shaped_status_label_counts_as_active() -> None:
    ghost = FakeGhost(
        member={
            "id": "m1",
            "email": "reader@example.com",
            "labels": [{"name": "product:archive-a"}, {"name": "payglue-active:polar"}],
            "note": "",
            "comped": True,
            "subscriptions": [{"id": "sub_comp_0", "status": "active", "price": {"nickname": "Complimentary", "amount": 0}}],
        }
    )
    _apply(ghost, "subscription-B", "grant")
    assert "payglue-active:polar" not in ghost.labels, "the old status shape is replaced, not doubled"

    _apply(ghost, "subscription-B", "revoke")

    assert ghost.member["comped"] is True
    assert "product:archive-a" in ghost.labels


def test_without_stripe_the_label_carries_the_access_the_same_way() -> None:
    ghost = FakeGhost(stripe_connected=False)

    _apply(ghost, "archive-A", "grant")
    _apply(ghost, "subscription-B", "grant")
    _apply(ghost, "subscription-B", "revoke")

    assert "payglue-active" in ghost.labels
    assert "product:archive-a" in ghost.labels

    _apply(ghost, "archive-A", "revoke")

    assert "payglue-active" not in ghost.labels
    assert "payglue-ended" in ghost.labels

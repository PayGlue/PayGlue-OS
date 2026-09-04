import json
import re

import pytest

from payglue_backend.core.errors import (
    CmsApplyEntitlementError,
    MissingCredentialsError,
)
from payglue_backend.core.models import CanonicalCustomer, EntitlementInstruction, TenantContext
from payglue_backend.webhooks.adapters.ghost import GhostCmsAdapter


ADMIN_KEY = "keyid:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class StubCredentialProvider:
    def get_credentials(
        self, tenant_ctx: TenantContext, provider_key: str
    ) -> dict[str, str]:
        assert tenant_ctx.tenant_slug == "tenant-a"
        assert provider_key == "ghost"
        return {
            "api_base_url": "https://ghost.test",
            "admin_api_key": ADMIN_KEY,
        }


class StubResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class StubHttpClient:
    """Configurable stub: GET calls return `get_response`, POST calls return `post_response`, PUT calls return `put_response`."""

    def __init__(
        self,
        get_response: StubResponse | None = None,
        post_response: StubResponse | None = None,
        put_response: StubResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self._get_response = get_response or StubResponse(200, json.dumps({"members": []}))
        self._post_response = post_response or StubResponse(201)
        self._put_response = put_response or StubResponse(200)
        self._error = error
        self.get_calls: list[dict[str, object]] = []
        self.post_calls: list[dict[str, object]] = []
        self.put_calls: list[dict[str, object]] = []

    def get(self, url: str, headers: dict[str, str]) -> StubResponse:
        self.get_calls.append({"url": url, "headers": headers})
        if self._error is not None:
            raise self._error
        return self._get_response

    def post(
        self, url: str, json_body: dict[str, object], headers: dict[str, str]
    ) -> StubResponse:
        self.post_calls.append({"url": url, "json_body": json_body, "headers": headers})
        if self._error is not None:
            raise self._error
        return self._post_response

    def put(
        self, url: str, json_body: dict[str, object], headers: dict[str, str]
    ) -> StubResponse:
        self.put_calls.append({"url": url, "json_body": json_body, "headers": headers})
        if self._error is not None:
            raise self._error
        return self._put_response


def _customer(email: str = "user@example.com", name: str | None = None) -> CanonicalCustomer:
    return CanonicalCustomer(email=email, name=name)


def _instruction(key: str = "tier.basic", action: str = "grant") -> EntitlementInstruction:
    return EntitlementInstruction(entitlement_key=key, action=action, quantity=1)


def _ctx() -> TenantContext:
    return TenantContext(tenant_slug="tenant-a")


def _assert_ghost_auth(headers: object) -> None:
    assert isinstance(headers, dict)
    assert re.match(
        r"^Ghost [A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$",
        headers["Authorization"],
    )
    assert headers["Accept-Version"] == "v5.0"


# --- apply_entitlement: new member (GET returns empty list → POST) ---

def test_apply_entitlement_creates_new_member() -> None:
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(), _instruction(), _ctx())

    assert len(client.get_calls) == 2
    assert "settings" in client.get_calls[0]["url"]
    assert "filter=email" in client.get_calls[1]["url"]
    assert len(client.post_calls) == 1
    assert len(client.put_calls) == 0

    post = client.post_calls[0]
    assert post["url"] == "https://ghost.test/ghost/api/admin/members/"
    member = post["json_body"]["members"][0]  # type: ignore[index]
    assert member["email"] == "user@example.com"
    # Stub's default GET response has no stripe_connect_account_id in settings,
    # so Ghost's own Stripe isn't connected and comped stays False. Access is
    # carried by the label either way (see GhostCmsAdapter.apply_entitlement).
    assert member["comped"] is False
    assert {"name": "source:payglue"} in member["labels"]
    assert {"name": "product:tier-basic"} in member["labels"]
    assert {"name": "payglue-active"} in member["labels"]
    _assert_ghost_auth(post["headers"])


def test_apply_entitlement_creates_member_with_name() -> None:
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(name="Max Mustermann"), _instruction(), _ctx())

    member = client.post_calls[0]["json_body"]["members"][0]  # type: ignore[index]
    assert member["name"] == "Max Mustermann"


def test_apply_entitlement_omits_name_when_absent() -> None:
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(), _instruction(), _ctx())

    member = client.post_calls[0]["json_body"]["members"][0]  # type: ignore[index]
    assert "name" not in member


# --- apply_entitlement: existing member (GET returns member → PUT) ---

def test_apply_entitlement_updates_existing_member() -> None:
    existing = json.dumps({"members": [{"id": "abc123", "email": "user@example.com"}]})
    client = StubHttpClient(get_response=StubResponse(200, existing))
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(), _instruction(), _ctx())

    assert len(client.get_calls) == 2
    assert len(client.post_calls) == 0
    assert len(client.put_calls) == 1

    put = client.put_calls[0]
    assert put["url"] == "https://ghost.test/ghost/api/admin/members/abc123/"
    member = put["json_body"]["members"][0]  # type: ignore[index]
    # Stub's GET response has no stripe_connect_account_id, so comped stays False.
    assert member["comped"] is False
    _assert_ghost_auth(put["headers"])


def test_apply_entitlement_revoke_sets_comped_false() -> None:
    client = StubHttpClient(
        get_response=StubResponse(200, json.dumps({"members": [{"id": "m1"}]})),
    )
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(), _instruction(action="revoke"), _ctx())

    member = client.put_calls[0]["json_body"]["members"][0]  # type: ignore[index]
    assert member["comped"] is False


def test_revoke_for_an_unknown_email_creates_nothing() -> None:
    # This used to create the member, which invented a cancellation for someone
    # who never bought anything. Reachable through the revoke-everything path
    # for providers that do not name the tier on a cancellation.
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(), _instruction(action="revoke"), _ctx())

    assert client.post_calls == []
    assert client.put_calls == []


# --- error handling ---

def test_apply_entitlement_raises_when_email_missing() -> None:
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    with pytest.raises(CmsApplyEntitlementError, match="email"):
        adapter.apply_entitlement(
            CanonicalCustomer(email=None, external_id="cus_001"),
            _instruction(),
            _ctx(),
        )


def test_apply_entitlement_raises_on_ghost_error_status() -> None:
    client = StubHttpClient(post_response=StubResponse(500, "boom"))
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    with pytest.raises(CmsApplyEntitlementError):
        adapter.apply_entitlement(_customer(), _instruction(), _ctx())


def test_apply_entitlement_raises_on_transport_error() -> None:
    client = StubHttpClient(error=RuntimeError("network down"))
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    with pytest.raises(CmsApplyEntitlementError):
        adapter.apply_entitlement(_customer(), _instruction(), _ctx())


# --- health check ---

def test_health_check_reports_success() -> None:
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    result = adapter.health_check(_ctx())

    assert result["ok"] is True
    assert result["code"] == "ok"
    assert "succeeded" in result["message"]
    assert len(client.get_calls) == 1
    assert client.get_calls[0]["url"] == "https://ghost.test/ghost/api/admin/site/"


def test_health_check_reports_http_failure() -> None:
    client = StubHttpClient(get_response=StubResponse(503))
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    result = adapter.health_check(_ctx())

    assert result["ok"] is False
    assert result["code"] == "http_503"


def test_health_check_raises_for_missing_required_credentials() -> None:
    class MissingCredsProvider:
        def get_credentials(
            self, tenant_ctx: TenantContext, provider_key: str
        ) -> dict[str, str]:
            del tenant_ctx, provider_key
            return {"api_base_url": "https://ghost.test"}

    adapter = GhostCmsAdapter(
        http_client=StubHttpClient(),
        credential_provider=MissingCredsProvider(),
    )

    with pytest.raises(MissingCredentialsError):
        adapter.health_check(_ctx())


# --- paywall_check: who the gate lets through (PG-229) ---
#
# Ghost knows three member states: free, paid, comped. All three plus the
# label have to be covered, because the gate is the only thing between a
# reader and content somebody paid for.


def _member_response(**fields: object) -> StubResponse:
    member: dict[str, object] = {"email": "user@example.com", "status": "free", "labels": []}
    member.update(fields)
    return StubResponse(200, json.dumps({"members": [member]}))


def _check(response: StubResponse) -> dict[str, object]:
    adapter = GhostCmsAdapter(
        http_client=StubHttpClient(get_response=response),
        credential_provider=StubCredentialProvider(),
    )
    return adapter.paywall_check(email="user@example.com", tenant_ctx=_ctx())


def test_paywall_check_lets_a_stripe_subscriber_through() -> None:
    # A real Stripe subscriber is status "paid" and NOT comped, and carries no
    # PayGlue label because PayGlue never touched them. Before PG-229 they were
    # locked out of a paywall on their own publication.
    assert _check(_member_response(status="paid", comped=False))["active"] is True


def test_paywall_check_lets_a_comped_member_through() -> None:
    assert _check(_member_response(status="comped", comped=True))["active"] is True


def test_paywall_check_lets_the_bare_status_label_through() -> None:
    # The label written from PG-229 onwards: status only, no provider in it.
    assert _check(
        _member_response(labels=[{"name": "payglue-active"}, {"name": "payglue-provider:polar"}])
    )["active"] is True


def test_paywall_check_still_lets_the_old_provider_label_through() -> None:
    # Members created before PG-229 carry payglue-active:<provider>. There is
    # deliberately no backfill in customer publications, so the old shape has
    # to keep working for as long as those members exist.
    assert _check(_member_response(labels=[{"name": "payglue-active:polar"}]))["active"] is True


def test_paywall_check_keeps_a_free_member_out() -> None:
    result = _check(_member_response(labels=[{"name": "source:payglue"}]))
    assert result["active"] is False


def test_paywall_check_keeps_an_unknown_email_out() -> None:
    response = StubResponse(200, json.dumps({"members": []}))
    assert _check(response)["active"] is False


# --- labels written on grant and removed on revoke (PG-229) ---


def test_grant_writes_status_and_provider_as_separate_labels() -> None:
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(), _instruction(), _ctx())

    labels = client.post_calls[0]["json_body"]["members"][0]["labels"]  # type: ignore[index]
    assert {"name": "payglue-active"} in labels
    assert {"name": "payglue-provider:payglue"} in labels


def test_revoke_removes_the_status_label() -> None:
    # The PUT sends the full label set, so leaving payglue-active out of it is
    # what actually removes access. Nothing else revokes it, which is why this
    # has a test of its own.
    client = StubHttpClient(
        get_response=StubResponse(200, json.dumps({"members": [{"id": "m1"}]})),
    )
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(), _instruction(action="revoke"), _ctx())

    labels = client.put_calls[0]["json_body"]["members"][0]["labels"]  # type: ignore[index]
    assert {"name": "payglue-active"} not in labels


# --- what an ended membership looks like afterwards (PG-271) ---


def _revoke_with_note(note: str, occurred_at: str = "2026-08-14") -> dict:
    client = StubHttpClient(
        get_response=StubResponse(200, json.dumps({"members": [{"id": "m1", "note": note}]})),
    )
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())
    instruction = EntitlementInstruction(
        entitlement_key="tier.basic",
        action="revoke",
        quantity=1,
        metadata={"_provider": "polar", "_event_id": "evt_9", "_occurred_at": occurred_at},
    )
    adapter.apply_entitlement(_customer(), instruction, _ctx())
    return client.put_calls[0]["json_body"]["members"][0]  # type: ignore[index,return-value]


def test_revoke_marks_the_member_as_ended_and_keeps_the_provider() -> None:
    # Without these two, a cancellation, a grant that never ran and a
    # never-customer all leave the same member behind.
    member = _revoke_with_note("Direct via PayGlue | Provider: polar\nProduct: prod_1")

    assert {"name": "payglue-ended"} in member["labels"]
    assert {"name": "payglue-provider:polar"} in member["labels"]


def test_the_purchase_line_carries_its_date_too() -> None:
    # Same shape as the ending, so the note reads as a timeline rather than an
    # id with a date underneath it.
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())
    instruction = EntitlementInstruction(
        entitlement_key="tier.basic",
        action="grant",
        quantity=1,
        metadata={"_provider": "polar", "_event_id": "evt_1", "_occurred_at": "2026-08-14"},
    )

    adapter.apply_entitlement(_customer(), instruction, _ctx())

    member = client.post_calls[0]["json_body"]["members"][0]  # type: ignore[index]
    assert member["note"].endswith("Order: 2026-08-14 | Event: evt_1")


def test_a_purchase_without_a_date_still_names_its_event() -> None:
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())
    instruction = EntitlementInstruction(
        entitlement_key="tier.basic",
        action="grant",
        quantity=1,
        metadata={"_provider": "polar", "_event_id": "evt_1"},
    )

    adapter.apply_entitlement(_customer(), instruction, _ctx())

    member = client.post_calls[0]["json_body"]["members"][0]  # type: ignore[index]
    assert member["note"].endswith("Order | Event: evt_1")


def test_a_purchase_with_neither_date_nor_event_writes_no_order_line() -> None:
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(), _instruction(), _ctx())

    member = client.post_calls[0]["json_body"]["members"][0]  # type: ignore[index]
    assert "Order" not in member["note"]


def test_ended_label_does_not_open_the_paywall() -> None:
    response = StubResponse(
        200,
        json.dumps({"members": [{"status": "free", "comped": False, "labels": [
            {"name": "payglue-ended"},
            {"name": "payglue-provider:polar"},
        ]}]}),
    )
    assert _check(response)["active"] is False


def test_ending_adds_the_date_under_the_purchase_note() -> None:
    member = _revoke_with_note("Direct via PayGlue | Provider: polar\nProduct: prod_1\nOrder: evt_1")

    assert member["note"] == (
        "Direct via PayGlue | Provider: polar\n"
        "Product: prod_1\n"
        "Order: evt_1\n"
        "Ended: 2026-08-14 | Event: evt_9"
    )


def test_a_second_ending_replaces_the_first_instead_of_stacking() -> None:
    member = _revoke_with_note(
        "Direct via PayGlue | Provider: polar\nProduct: prod_1\nEnded: 2026-01-01 | Event: evt_0"
    )

    assert member["note"].count("Ended:") == 1
    assert member["note"].endswith("Ended: 2026-08-14 | Event: evt_9")


def test_ending_without_a_date_still_records_that_it_ended() -> None:
    # Events queued before this shipped carry no date, and the newsletter path
    # builds its instructions without one.
    member = _revoke_with_note("Product: prod_1", occurred_at="")

    assert member["note"].endswith("Ended | Event: evt_9")


def test_the_note_stays_within_the_length_ghost_accepts() -> None:
    member = _revoke_with_note("\n".join(f"Line {i} {'x' * 40}" for i in range(20)))

    assert len(member["note"]) <= 500
    assert member["note"].endswith("Ended: 2026-08-14 | Event: evt_9")


def test_a_repeat_purchase_clears_the_ending() -> None:
    # The note travels with the update now, so the ending has to go when the
    # member buys again. A stale "Ended" line would be worse than none.
    client = StubHttpClient(
        get_response=StubResponse(
            200,
            json.dumps({"members": [{"id": "m1", "note": "Product: prod_1\nEnded: 2026-01-01"}]}),
        ),
    )
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(), _instruction(), _ctx())

    member = client.put_calls[0]["json_body"]["members"][0]  # type: ignore[index]
    assert "Ended" not in member["note"]
    assert {"name": "payglue-active"} in member["labels"]

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
    # so Ghost's own Stripe isn't connected -> comped stays False and access is
    # tracked via a payglue-active label instead (see GhostCmsAdapter.apply_entitlement).
    assert member["comped"] is False
    assert {"name": "source:payglue"} in member["labels"]
    assert {"name": "product:tier-basic"} in member["labels"]
    assert {"name": "payglue-active:payglue"} in member["labels"]
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
    client = StubHttpClient()
    adapter = GhostCmsAdapter(http_client=client, credential_provider=StubCredentialProvider())

    adapter.apply_entitlement(_customer(), _instruction(action="revoke"), _ctx())

    member = client.post_calls[0]["json_body"]["members"][0]  # type: ignore[index]
    assert member["comped"] is False


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

import json
from urllib.parse import parse_qs, urlparse

import pytest

from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks.adapters.gumroad import GumroadPaymentAdapter

CURRENT = "https://api.example.com/webhooks/gumroad?tenant=tenant-a&key=new"
OLD = "https://api.example.com/webhooks/gumroad?tenant=tenant-a"


class StubCredentialProvider:
    def get_credentials(self, tenant_ctx: TenantContext, provider_key: str) -> dict[str, str]:
        return {"access_token": "token", "application_secret": "secret"}


class FakeGumroad:
    """Answers the resource_subscriptions calls and records them."""

    def __init__(self, existing: dict[str, list[dict]]) -> None:
        self.existing = existing
        self.calls: list[tuple[str, str, dict]] = []

    def urlopen(self, req, timeout=None):
        url = urlparse(req.full_url)
        params = parse_qs(req.data.decode() if req.data else url.query)
        flat = {key: values[0] for key, values in params.items()}
        self.calls.append((req.get_method(), url.path, flat))
        if req.get_method() == "GET":
            body = {"success": True, "resource_subscriptions": self.existing.get(flat["resource_name"], [])}
        else:
            body = {"success": True}
        return _Response(body)


class _Response:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


@pytest.fixture
def adapter() -> GumroadPaymentAdapter:
    return GumroadPaymentAdapter(credential_provider=StubCredentialProvider())


def test_registration_uses_put(adapter, monkeypatch) -> None:
    fake = FakeGumroad({})
    monkeypatch.setattr("urllib.request.urlopen", fake.urlopen)

    result = adapter.register_webhook_subscriptions(TenantContext(tenant_slug="tenant-a"), CURRENT)

    assert result == {"registered": ["sale", "cancellation", "subscription_ended"], "failed": []}
    created = [call for call in fake.calls if call[0] == "PUT"]
    assert [call[2]["resource_name"] for call in created] == ["sale", "cancellation", "subscription_ended"]
    assert all(call[1] == "/v2/resource_subscriptions" and call[2]["post_url"] == CURRENT for call in created)


def test_registration_replaces_an_older_address_of_the_same_tenant(adapter, monkeypatch) -> None:
    fake = FakeGumroad(
        {
            "sale": [
                {"id": "old-sale", "post_url": OLD},
                {"id": "other-tenant", "post_url": "https://api.example.com/webhooks/gumroad?tenant=tenant-b"},
                {"id": "foreign", "post_url": "https://hooks.example.org/gumroad?tenant=tenant-a"},
            ],
            "cancellation": [{"id": "old-cancel", "post_url": OLD}],
            "subscription_ended": [
                {"id": "internal-host", "post_url": "https://internal.example.net/webhooks/gumroad?tenant=tenant-a&key=new"}
            ],
        }
    )
    monkeypatch.setattr("urllib.request.urlopen", fake.urlopen)

    adapter.register_webhook_subscriptions(TenantContext(tenant_slug="tenant-a"), CURRENT)

    deleted = [call[1] for call in fake.calls if call[0] == "DELETE"]
    assert deleted == [
        "/v2/resource_subscriptions/old-sale",
        "/v2/resource_subscriptions/old-cancel",
        "/v2/resource_subscriptions/internal-host",
    ]


def test_registration_keeps_a_current_subscription(adapter, monkeypatch) -> None:
    fake = FakeGumroad({"sale": [{"id": "current", "post_url": CURRENT}, {"id": "twin", "post_url": CURRENT}]})
    monkeypatch.setattr("urllib.request.urlopen", fake.urlopen)

    result = adapter.register_webhook_subscriptions(TenantContext(tenant_slug="tenant-a"), CURRENT)

    assert "sale" in result["registered"]
    assert [call[1] for call in fake.calls if call[0] == "DELETE"] == ["/v2/resource_subscriptions/twin"]
    assert [call[2]["resource_name"] for call in fake.calls if call[0] == "PUT"] == [
        "cancellation",
        "subscription_ended",
    ]


def test_registration_reports_a_failed_resource(adapter, monkeypatch) -> None:
    def broken(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr("urllib.request.urlopen", broken)

    result = adapter.register_webhook_subscriptions(TenantContext(tenant_slug="tenant-a"), CURRENT)

    assert result == {"registered": [], "failed": ["sale", "cancellation", "subscription_ended"]}

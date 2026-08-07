"""PG-147: Creem's /v1/subscriptions/search and /v1/transactions/search do
not support a customer_id filter (verified against Creem's OpenAPI spec) --
they silently return a page of ALL items across the whole PayGlue Creem
account. These functions must filter client-side or every viewer of the
Billing page could see other customers' subscriptions/invoices."""
from payglue_backend.tenants.views import (
    _creem_fetch_subscriptions,
    _creem_fetch_transactions,
)


def _fake_get_factory(items: list[dict]):
    def _fake_get(url: str, api_key: str) -> dict:
        return {"items": items}

    return _fake_get


def test_fetch_subscriptions_filters_out_other_customers(monkeypatch) -> None:
    items = [
        {"id": "sub_1", "customer": "cust_a"},
        {"id": "sub_2", "customer": "cust_b"},
        {"id": "sub_3", "customer": {"id": "cust_a"}},
    ]
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._get", _fake_get_factory(items)
    )

    result = _creem_fetch_subscriptions("cust_a", "api_key", "https://api.creem.io", sandbox=False)

    assert [item["id"] for item in result] == ["sub_1", "sub_3"]


def test_fetch_transactions_filters_out_other_customers(monkeypatch) -> None:
    items = [
        {"id": "txn_1", "customer": "cust_a"},
        {"id": "txn_2", "customer": "cust_b"},
    ]
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._get", _fake_get_factory(items)
    )

    result = _creem_fetch_transactions("cust_a", "api_key", "https://api.creem.io", sandbox=False)

    assert [item["id"] for item in result] == ["txn_1"]


def test_fetch_transactions_merges_a_second_page_when_present(monkeypatch) -> None:
    """Found live (PG-141 test): a real, older transaction for the customer
    simply wasn't on page 1 with enough transactions in the whole PayGlue
    Creem account -- the exact failure PG-147/PG-149's docstring already
    warned about. Page 2+ requests are additive/best-effort (unverified
    param name), so this only needs to prove that when a further page
    *does* return something new, it gets merged in."""
    page_1_items = [{"id": "txn_1", "customer": "cust_a"}]
    page_2_items = [{"id": "txn_0_older", "customer": "cust_a"}]

    def _fake_get(url: str, api_key: str) -> dict:
        if "page=2" in url:
            return {"items": page_2_items}
        if "page=" in url:
            return {"items": []}
        return {"items": page_1_items}

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)

    result = _creem_fetch_transactions("cust_a", "api_key", "https://api.creem.io", sandbox=False)

    assert {item["id"] for item in result} == {"txn_1", "txn_0_older"}


def test_fetch_transactions_stops_when_a_page_repeats_page_1(monkeypatch) -> None:
    """If the guessed pagination param is wrong or unsupported, Creem likely
    just returns page 1's own items again (or nothing) -- must stop rather
    than loop pointlessly or duplicate results."""
    items = [{"id": "txn_1", "customer": "cust_a"}]
    calls: list[str] = []

    def _fake_get(url: str, api_key: str) -> dict:
        calls.append(url)
        return {"items": items}

    monkeypatch.setattr("payglue_backend.authn.creem_access._get", _fake_get)

    result = _creem_fetch_transactions("cust_a", "api_key", "https://api.creem.io", sandbox=False)

    assert [item["id"] for item in result] == ["txn_1"]
    # Page 1 + exactly one page-2 probe that comes back with nothing new.
    assert len(calls) == 2


def test_fetch_subscriptions_tags_sandbox_only_on_matching_items(monkeypatch) -> None:
    items = [
        {"id": "sub_1", "customer": "cust_a"},
        {"id": "sub_2", "customer": "cust_b"},
    ]
    monkeypatch.setattr(
        "payglue_backend.authn.creem_access._get", _fake_get_factory(items)
    )

    result = _creem_fetch_subscriptions("cust_a", "api_key", "https://test-api.creem.io", sandbox=True)

    assert len(result) == 1
    assert result[0]["_sandbox"] is True

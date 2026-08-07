# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-202: one-click connection test. run_mapping_test fires a synthetic event
for a mapping through the real resolver + CMS adapter (mocked here), and the
API endpoint is Owner/Admin-only, validates the email, and records an audit
event -- without touching the webhook log or idempotency chain."""
import json
from dataclasses import dataclass

import pytest
from django.test import Client

from payglue_backend.core.errors import CmsApplyEntitlementError
from payglue_backend.tenants.models import (
    PublicAuditEvent,
    Tenant,
    TenantMembership,
    UserProfile,
)
from payglue_backend.webhooks import wiring
from payglue_backend.webhooks.models import ProductMapping, WebhookInboundEvent
from payglue_backend.webhooks.test_events import run_mapping_test

pytestmark = pytest.mark.django_db


class _FakeCms:
    def __init__(self) -> None:
        self.calls: list = []

    def apply_entitlement(self, customer, instruction, tenant_ctx) -> None:
        self.calls.append((customer.email, instruction.entitlement_key, instruction.action))


class _FailingCms:
    def apply_entitlement(self, customer, instruction, tenant_ctx) -> None:
        raise CmsApplyEntitlementError("Ghost Admin API key is invalid")


def _mapping(**overrides) -> ProductMapping:
    defaults = dict(
        tenant_slug="acme",
        payment_provider="patreon",
        event_type="subscription.active",
        external_product_id="tier_1",
        entitlement_key="vip",
        action="grant",
        is_active=True,
    )
    defaults.update(overrides)
    return ProductMapping.objects.create(**defaults)


def _use_cms(monkeypatch, cms) -> None:
    monkeypatch.setattr(wiring, "get_tenant_cms_provider_key", lambda slug: "ghost")
    monkeypatch.setattr(wiring, "get_cms_adapter", lambda key: cms)


# --- service level -------------------------------------------------------


def test_run_mapping_test_applies_entitlement(monkeypatch) -> None:
    mapping = _mapping()
    cms = _FakeCms()
    _use_cms(monkeypatch, cms)

    result = run_mapping_test(mapping, "you+test@example.com")

    assert result["ok"] is True
    assert result["applied"] == 1
    assert result["entitlements"] == [{"entitlement_key": "vip", "action": "grant"}]
    assert cms.calls == [("you+test@example.com", "vip", "grant")]


def test_run_mapping_test_reports_no_mapping(monkeypatch) -> None:
    mapping = _mapping(is_active=False)  # resolver ignores inactive mappings
    _use_cms(monkeypatch, _FakeCms())

    result = run_mapping_test(mapping, "you+test@example.com")

    assert result["ok"] is False
    assert result["applied"] == 0
    assert "mapping" in result["error"].lower()


def test_run_mapping_test_surfaces_ghost_error(monkeypatch) -> None:
    mapping = _mapping()
    _use_cms(monkeypatch, _FailingCms())

    result = run_mapping_test(mapping, "you+test@example.com")

    assert result["ok"] is False
    assert "Ghost Admin API key is invalid" in result["error"]


def test_run_mapping_test_does_not_write_webhook_log(monkeypatch) -> None:
    mapping = _mapping()
    _use_cms(monkeypatch, _FakeCms())

    run_mapping_test(mapping, "you+test@example.com")

    # No inbound event / idempotency pollution from a test run.
    assert WebhookInboundEvent.objects.count() == 0


# --- API level -----------------------------------------------------------


@dataclass(frozen=True)
class _StubClaims:
    firebase_uid: str
    email: str


class _StubVerifier:
    def __init__(self, claims: _StubClaims) -> None:
        self._claims = claims

    def verify(self, token: str) -> _StubClaims:
        del token
        return self._claims


def _auth(monkeypatch, *, slug: str, role: str, uid: str) -> dict:
    tenant, _ = Tenant.objects.get_or_create(slug=slug, defaults={"schema_name": slug.replace("-", "_")})
    profile = UserProfile.objects.create(firebase_uid=f"uid-{uid}", email=f"{uid}@example.com")
    TenantMembership.objects.create(tenant=tenant, user_profile=profile, role=role)
    monkeypatch.setattr(
        "payglue_backend.authn.authentication.get_auth_token_verifier",
        lambda: _StubVerifier(_StubClaims(firebase_uid=profile.firebase_uid, email=profile.email)),
    )
    return {"HTTP_AUTHORIZATION": "Bearer stub.header.signature"}


def _post(slug: str, mapping_id, headers: dict, body: dict):
    return Client().post(
        f"/t/{slug}/api/v1/mappings/{mapping_id}/test",
        data=json.dumps(body),
        content_type="application/json",
        **headers,
    )


def test_api_owner_can_run_test_and_audit_is_written(monkeypatch) -> None:
    mapping = _mapping()
    _use_cms(monkeypatch, _FakeCms())
    headers = _auth(monkeypatch, slug="acme", role=TenantMembership.Role.OWNER, uid="owner")

    resp = _post("acme", mapping.id, headers, {"test_email": "you+test@example.com"})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert PublicAuditEvent.objects.filter(
        event_type=PublicAuditEvent.EventType.TEST_EVENT_SENT
    ).count() == 1


def test_api_rejects_invalid_email(monkeypatch) -> None:
    mapping = _mapping()
    _use_cms(monkeypatch, _FakeCms())
    headers = _auth(monkeypatch, slug="acme", role=TenantMembership.Role.OWNER, uid="owner2")

    resp = _post("acme", mapping.id, headers, {"test_email": "not-an-email"})

    assert resp.status_code == 400


def test_api_unknown_mapping_is_404(monkeypatch) -> None:
    headers = _auth(monkeypatch, slug="acme", role=TenantMembership.Role.OWNER, uid="owner3")

    resp = _post("acme", 999999, headers, {"test_email": "you+test@example.com"})

    assert resp.status_code == 404


def test_api_mapping_of_other_tenant_is_404(monkeypatch) -> None:
    Tenant.objects.get_or_create(slug="acme", defaults={"schema_name": "acme"})
    other_mapping = _mapping(tenant_slug="beta")
    _use_cms(monkeypatch, _FakeCms())
    headers = _auth(monkeypatch, slug="acme", role=TenantMembership.Role.OWNER, uid="owner4")

    resp = _post("acme", other_mapping.id, headers, {"test_email": "you+test@example.com"})

    assert resp.status_code == 404

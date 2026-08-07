# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
import pytest
from django.test import Client

from payglue_backend.authn.creem_access import CreemAccessError, CreemLicenseAlreadyUsedError
from payglue_backend.authn.polar_access import PolarAccessError
from payglue_backend.tenants.models import AccessRedemption, InvitationGrant


pytestmark = pytest.mark.django_db


def _creem_grant(email: str, key: str) -> InvitationGrant:
    return InvitationGrant.objects.create(
        email=email, license_key=key, source=InvitationGrant.Source.CREEM_CHECKOUT
    )


def _validate(email: str, key: str):
    return Client().post(
        "/api/v1/auth/access/validate",
        data={"email": email, "license_key": key},
        content_type="application/json",
    )


def test_creem_license_key_is_activated_at_creem_on_redemption(settings, monkeypatch) -> None:
    """A Creem license key redeemed at signup should be activated at Creem so its
    dashboard flips to 'active' and we store the returned instance id."""
    settings.CREEM_API_KEY = "creem_live_key"
    _creem_grant("buyer@example.com", "CREEM-KEY-1")
    calls = {}

    def _fake_activate(key, instance_name, api_key, sandbox=False):
        calls.update(key=key, instance_name=instance_name, api_key=api_key)
        return {"instance": {"id": "inst_123"}}

    monkeypatch.setattr("payglue_backend.authn.views.activate_creem_license", _fake_activate)

    resp = _validate("buyer@example.com", "CREEM-KEY-1")

    assert resp.status_code == 200
    assert calls == {"key": "CREEM-KEY-1", "instance_name": "buyer@example.com", "api_key": "creem_live_key"}
    grant = InvitationGrant.objects.get(email="buyer@example.com")
    assert grant.creem_license_instance_id == "inst_123"


def test_creem_activation_error_does_not_block_signup(settings, monkeypatch) -> None:
    """A paying customer must never be locked out by a Creem API hiccup -- the
    activation is best-effort, the local AccessRedemption is the real guard."""
    settings.CREEM_API_KEY = "creem_live_key"
    _creem_grant("buyer2@example.com", "CREEM-KEY-2")

    def _raise(*_a, **_k):
        raise CreemAccessError("Creem API 500: boom")

    monkeypatch.setattr("payglue_backend.authn.views.activate_creem_license", _raise)

    resp = _validate("buyer2@example.com", "CREEM-KEY-2")

    assert resp.status_code == 200
    grant = InvitationGrant.objects.get(email="buyer2@example.com")
    assert grant.creem_license_instance_id == ""


def test_creem_already_activated_does_not_block_signup(settings, monkeypatch) -> None:
    """The checkout.completed webhook activates the key at purchase time, so
    'already activated' at signup is the normal case and must NOT block -- reuse
    is guarded locally by AccessRedemption."""
    settings.CREEM_API_KEY = "creem_live_key"
    _creem_grant("buyer3@example.com", "CREEM-KEY-3")

    def _raise(*_a, **_k):
        raise CreemLicenseAlreadyUsedError("license already activated")

    monkeypatch.setattr("payglue_backend.authn.views.activate_creem_license", _raise)

    resp = _validate("buyer3@example.com", "CREEM-KEY-3")

    assert resp.status_code == 200
    assert AccessRedemption.objects.filter(email="buyer3@example.com").exists()


def test_validate_sanitizes_provider_error_and_logs_the_raw_detail(
    monkeypatch: pytest.MonkeyPatch, settings, caplog: pytest.LogCaptureFixture
) -> None:
    """Found live (PG-142): a license key not in our own InvitationGrant table
    falls back to Polar, and Polar's raw error text ("Polar API 401: {...}")
    was reaching the signup form verbatim -- meaningless to a customer and
    looks like an internal leak. It must be replaced with a generic message,
    with the real detail only going to our own logs."""
    settings.POLAR_API_KEY = "polar_test_key"
    settings.POLAR_ORGANIZATION_ID = "org_test"

    def _fake_validate_license_key(license_key, api_key, organization_id, sandbox=False):
        raise PolarAccessError(
            'Polar API 401: {"error": "invalid_token", "error_description": '
            '"The access token provided is expired, revoked, malformed, or invalid for other reasons."}'
        )

    monkeypatch.setattr(
        "payglue_backend.authn.views.validate_license_key", _fake_validate_license_key
    )

    resp = Client().post(
        "/api/v1/auth/access/validate",
        data={"email": "new-customer@example.com", "license_key": "SOME-FAKE-KEY-1234"},
        content_type="application/json",
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "Polar API" not in detail
    assert "invalid_token" not in detail
    assert "invalid or has expired" in detail.lower()
    assert any("Polar API 401" in record.message for record in caplog.records)


def test_dev_bypass_license_key_creates_a_grant_without_touching_creem_or_polar(
    settings,
) -> None:
    """PG-142: signup testing without a real Creem/Polar purchase needs a
    secret that's never shipped to the frontend -- unlike the old client-side
    "dev" string, which was readable straight out of the public JS bundle."""
    settings.DEV_BYPASS_LICENSE_KEY = "s3cr3t-only-we-know"

    resp = Client().post(
        "/api/v1/auth/access/validate",
        data={"email": "tester@example.com", "license_key": "s3cr3t-only-we-know"},
        content_type="application/json",
    )

    assert resp.status_code == 200
    grant = InvitationGrant.objects.get(email="tester@example.com")
    assert grant.source == InvitationGrant.Source.MANUAL
    assert grant.consumed_at is None


def test_dev_bypass_license_key_can_be_reused_for_a_different_email(settings) -> None:
    """The same shared dev secret must work for many distinct test emails,
    not just the first one -- unlike a real license key, which is single-use
    and keyed by AccessRedemption.redemption_id on its own value."""
    settings.DEV_BYPASS_LICENSE_KEY = "s3cr3t-only-we-know"
    client = Client()

    first = client.post(
        "/api/v1/auth/access/validate",
        data={"email": "tester-one@example.com", "license_key": "s3cr3t-only-we-know"},
        content_type="application/json",
    )
    second = client.post(
        "/api/v1/auth/access/validate",
        data={"email": "tester-two@example.com", "license_key": "s3cr3t-only-we-know"},
        content_type="application/json",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert InvitationGrant.objects.filter(email="tester-one@example.com").exists()
    assert InvitationGrant.objects.filter(email="tester-two@example.com").exists()
    assert AccessRedemption.objects.filter(
        redemption_id__in=["dev-bypass:tester-one@example.com", "dev-bypass:tester-two@example.com"]
    ).count() == 2


def test_dev_bypass_disabled_when_setting_is_unset(settings) -> None:
    """The literal word people might guess ("dev") must not work unless a
    real secret has actually been configured in Railway -- an unset (empty)
    DEV_BYPASS_LICENSE_KEY disables the branch entirely, falling through to
    the normal Polar path (and failing, since Polar isn't configured here)."""
    settings.DEV_BYPASS_LICENSE_KEY = ""
    settings.POLAR_API_KEY = ""

    resp = Client().post(
        "/api/v1/auth/access/validate",
        data={"email": "tester@example.com", "license_key": "dev"},
        content_type="application/json",
    )

    assert resp.status_code == 503
    assert not InvitationGrant.objects.filter(email="tester@example.com").exists()

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Creem license activation: an 'already activated / limit reached' rejection is
reclassified as CreemLicenseAlreadyUsedError so the signup flow can block a
re-redemption, while any other API error stays a plain CreemAccessError (which
the signup flow logs-and-continues on)."""
import pytest

from payglue_backend.authn import creem_access
from payglue_backend.authn.creem_access import (
    CreemAccessError,
    CreemLicenseAlreadyUsedError,
    activate_license,
)


def test_already_used_error_is_reclassified(monkeypatch) -> None:
    def _raise(url, api_key, body):
        raise CreemAccessError("Creem API 409: license already activated")

    monkeypatch.setattr(creem_access, "_post", _raise)

    with pytest.raises(CreemLicenseAlreadyUsedError):
        activate_license("KEY", "instance", "api-key")


def test_generic_error_passes_through(monkeypatch) -> None:
    def _raise(url, api_key, body):
        raise CreemAccessError("Creem API 500: server error")

    monkeypatch.setattr(creem_access, "_post", _raise)

    with pytest.raises(CreemAccessError) as excinfo:
        activate_license("KEY", "instance", "api-key")
    assert not isinstance(excinfo.value, CreemLicenseAlreadyUsedError)


def test_success_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        creem_access, "_post", lambda url, api_key, body: {"instance": {"id": "inst_1"}}
    )

    assert activate_license("KEY", "instance", "api-key") == {"instance": {"id": "inst_1"}}

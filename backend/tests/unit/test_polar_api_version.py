# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Polar rotates its default API version every quarter. Every request we send
has to carry the version we tested against, or the contract moves under us."""
from payglue_backend.authn import polar_access


def test_every_polar_request_pins_the_api_version() -> None:
    assert polar_access._HEADERS["Polar-Version"] == polar_access.POLAR_API_VERSION
    assert polar_access.POLAR_API_VERSION == "2026-04"

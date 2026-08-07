"""Public addresses come from configuration, never from a literal (PG-238).

The failure this guards against was not subtle: a self-hosted install put our
dashboard in its own customers' emails and accepted only our hosts as a checkout
return target, so its own checkout could never complete.

The rule these tests pin is that an unconfigured install produces *nothing*
rather than something belonging to us. An empty link can be left out. A link to
the wrong company cannot be taken back.
"""

import pytest
from django.test import override_settings

from payglue_backend.core.public_urls import api_base, app_base, app_host, app_url
from payglue_backend.tenants.views import _allowed_return_hosts

CONFIGURED = "https://payglue.selfhosted.example"


class TestUnconfigured:
    @override_settings(PUBLIC_APP_BASE_URL="", PUBLIC_API_BASE_URL="")
    def test_everything_is_empty_rather_than_ours(self) -> None:
        assert app_base() == ""
        assert api_base() == ""
        assert app_host() == ""
        assert app_url("/t/acme/team") == ""

    @override_settings(PUBLIC_APP_BASE_URL="", CHECKOUT_RETURN_HOSTS="")
    def test_only_loopback_is_accepted_as_a_return_host(self) -> None:
        # No baked-in host means no ready-made redirect target sitting in the
        # public source either.
        assert _allowed_return_hosts() == {"localhost", "127.0.0.1"}


class TestConfigured:
    @override_settings(PUBLIC_APP_BASE_URL=CONFIGURED)
    def test_builds_absolute_dashboard_links(self) -> None:
        assert app_url("/t/acme/team") == f"{CONFIGURED}/t/acme/team"
        assert app_url("t/acme/team") == f"{CONFIGURED}/t/acme/team"
        assert app_url() == CONFIGURED

    @override_settings(PUBLIC_APP_BASE_URL=CONFIGURED + "/")
    def test_a_trailing_slash_does_not_double_up(self) -> None:
        # Whoever pastes the value in will sooner or later paste it with a
        # slash, and //t/acme is a 404.
        assert app_url("/t/acme") == f"{CONFIGURED}/t/acme"
        assert "//t/" not in app_url("/t/acme")

    @override_settings(PUBLIC_APP_BASE_URL="https://dash.example.com:8443")
    def test_host_ignores_scheme_and_port(self) -> None:
        assert app_host() == "dash.example.com"

    @override_settings(PUBLIC_APP_BASE_URL=CONFIGURED, CHECKOUT_RETURN_HOSTS="")
    def test_the_configured_dashboard_is_a_valid_return_host(self) -> None:
        assert "payglue.selfhosted.example" in _allowed_return_hosts()

    @override_settings(PUBLIC_APP_BASE_URL=CONFIGURED, CHECKOUT_RETURN_HOSTS=" extra.example ,  second.example ")
    def test_extra_return_hosts_are_trimmed_and_lowercased(self) -> None:
        hosts = _allowed_return_hosts()
        assert "extra.example" in hosts
        assert "second.example" in hosts
        assert " extra.example " not in hosts

    @override_settings(PUBLIC_APP_BASE_URL=CONFIGURED, CHECKOUT_RETURN_HOSTS="")
    def test_a_lookalike_host_is_still_rejected(self) -> None:
        # The allowlist is compared against a parsed hostname, so a suffix
        # trick must not slip through.
        assert "payglue.selfhosted.example.evil.test" not in _allowed_return_hosts()


@pytest.mark.parametrize("value", ["", "   "])
@override_settings(PUBLIC_APP_BASE_URL="")
def test_blank_configuration_is_treated_as_unset(value: str) -> None:
    with override_settings(PUBLIC_APP_BASE_URL=value):
        assert app_url("/x") == ""

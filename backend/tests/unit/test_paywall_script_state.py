# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Whether *this tenant's* paywall script is on the Ghost site (PG-256).

The check used to be `"/paywall.js" in html`, which passes on anybody's script.
Found while testing PG-254 on staging: a tenant pointing at a Ghost site that
carries the production script was told "Installed, script is active in Ghost",
for a script wired to a different backend and a different publication.

Two rules pull against each other here and both have to hold. The host must not
be checked, because a self-hosted installation serves the file from its own
domain (PG-238). The publication must be checked, because otherwise a stranger's
script counts as yours.
"""

import pytest

from payglue_backend.webhooks.views import _paywall_script_state

SNIPPET = '<script src="https://api.payglue.io/paywall.js" data-org="{org}"></script>'


def test_our_own_snippet_counts() -> None:
    installed, detail = _paywall_script_state(SNIPPET.format(org="acme"), "acme")

    assert installed is True
    assert detail is None


def test_a_self_hosted_script_from_its_own_domain_still_counts() -> None:
    """The reason the host check was dropped in the first place. Whoever serves
    the file is the backend to talk to, so the domain proves nothing."""
    html = '<script src="https://blog.example.com/paywall.js" data-org="acme"></script>'

    assert _paywall_script_state(html, "acme")[0] is True


def test_another_publications_script_does_not_count() -> None:
    """The staging case. Right path, wrong publication: it would gate for
    somebody else, so reporting it as installed is worse than reporting
    nothing."""
    installed, detail = _paywall_script_state(SNIPPET.format(org="payglue"), "constrain")

    assert installed is False
    assert "different publication" in detail


def test_a_snippet_that_lost_its_publication_id_says_that_instead() -> None:
    """Different cause, different sentence: this is a snippet mangled on the way
    into the theme, not one copied from elsewhere."""
    installed, detail = _paywall_script_state(
        '<script src="https://api.payglue.io/paywall.js"></script>', "acme"
    )

    assert installed is False
    assert "no publication id" in detail


def test_an_unrelated_script_is_simply_not_it() -> None:
    """No message here. Nothing about this page suggests somebody tried."""
    installed, detail = _paywall_script_state(
        '<script src="https://cdn.example.com/analytics.js"></script>', "acme"
    )

    assert installed is False
    assert detail is None


def test_an_empty_page_is_not_it_either() -> None:
    assert _paywall_script_state("", "acme") == (False, None)


@pytest.mark.parametrize(
    "markup",
    [
        "<script data-org='acme' src='https://api.payglue.io/paywall.js'></script>",
        '<SCRIPT SRC="https://api.payglue.io/paywall.js" DATA-ORG="acme"></SCRIPT>',
        '<script   src = "https://api.payglue.io/paywall.js"   data-org = "acme" ></script>',
        '<script async src="https://api.payglue.io/paywall.js" data-org="acme"></script>',
    ],
)
def test_the_shapes_a_theme_editor_produces(markup: str) -> None:
    """Ghost's code injection field is hand-edited, and people reorder
    attributes, change quoting and add `async`. None of that changes what the
    script is."""
    assert _paywall_script_state(markup, "acme")[0] is True


def test_a_query_string_does_not_hide_the_path() -> None:
    html = '<script src="https://api.payglue.io/paywall.js?v=2" data-org="acme"></script>'

    assert _paywall_script_state(html, "acme")[0] is True


def test_the_right_script_wins_when_the_page_carries_two() -> None:
    """A publication that moved between environments can end up with both. The
    first one found decides today, so this pins the behaviour rather than
    leaving it to whichever order the theme happens to use."""
    html = SNIPPET.format(org="acme") + SNIPPET.format(org="other")

    assert _paywall_script_state(html, "acme")[0] is True

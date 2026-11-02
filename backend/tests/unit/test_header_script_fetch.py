# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Fetching the Ghost home page for the header-script check.

The stored site URL is the one the Ghost Admin API answers on. On Ghost(Pro)
with a custom domain that is the ghost.io address, and it answers the home
page with a redirect to the custom domain. The check refused every redirect
and reported "Could not reach https://<site>.ghost.io/: HTTP Error 302" while
the script sat correctly on the custom domain. Redirects are followed now, one
hop at a time, and every target must be a public http(s) host.
"""

import io
import urllib.error
from email.message import Message
from unittest import mock

import pytest

from payglue_backend.webhooks import views
from payglue_backend.webhooks.views import _UnsafeSiteURL, _fetch_site_root


def _redirect(url: str, location: str, code: int = 302) -> urllib.error.HTTPError:
    headers = Message()
    headers["Location"] = location
    return urllib.error.HTTPError(url, code, "Found", headers, io.BytesIO(b""))


class _Page:
    def __init__(self, html: str) -> None:
        self._html = html

    def read(self) -> bytes:
        return self._html.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _opener(responses: dict[str, object]):
    """An opener that answers by URL: a page, or a redirect to raise."""
    requested: list[str] = []

    class _Opener:
        def open(self, req, timeout=None):
            requested.append(req.full_url)
            answer = responses[req.full_url]
            if isinstance(answer, Exception):
                raise answer
            return answer

    return _Opener(), requested


def test_ghost_pro_redirect_to_the_custom_domain_is_followed() -> None:
    opener, requested = _opener({
        "https://acme.ghost.io/": _redirect("https://acme.ghost.io/", "https://www.acme.com/"),
        "https://www.acme.com/": _Page('<script src="https://api.payglue.io/paywall.js" data-org="acme"></script>'),
    })
    with mock.patch("urllib.request.build_opener", return_value=opener):
        url, html = _fetch_site_root("https://acme.ghost.io")

    assert url == "https://www.acme.com/"
    assert 'data-org="acme"' in html
    assert requested == ["https://acme.ghost.io/", "https://www.acme.com/"]


def test_a_site_without_redirect_is_fetched_once() -> None:
    opener, requested = _opener({"https://blog.example.com/": _Page("<html></html>")})
    with mock.patch("urllib.request.build_opener", return_value=opener):
        url, _ = _fetch_site_root("https://blog.example.com/ghost/api/admin/")

    assert url == "https://blog.example.com/"
    assert requested == ["https://blog.example.com/"]


@pytest.mark.parametrize("target", ["http://127.0.0.1/", "http://10.0.0.5/", "http://localhost/", "http://db.internal/", "file:///etc/passwd"])
def test_a_redirect_to_a_private_or_odd_target_is_refused(target: str) -> None:
    opener, requested = _opener({"https://acme.ghost.io/": _redirect("https://acme.ghost.io/", target)})
    with mock.patch("urllib.request.build_opener", return_value=opener), pytest.raises(_UnsafeSiteURL):
        _fetch_site_root("https://acme.ghost.io/")

    assert requested == ["https://acme.ghost.io/"]


def test_a_redirect_loop_gives_up() -> None:
    opener, requested = _opener({
        "https://a.example.com/": _redirect("https://a.example.com/", "https://b.example.com/"),
        "https://b.example.com/": _redirect("https://b.example.com/", "https://a.example.com/"),
    })
    with mock.patch("urllib.request.build_opener", return_value=opener), pytest.raises(ValueError, match="redirects"):
        _fetch_site_root("https://a.example.com/")

    assert len(requested) == views._MAX_SITE_REDIRECTS + 1


def test_an_error_that_is_not_a_redirect_is_passed_on() -> None:
    error = urllib.error.HTTPError("https://acme.ghost.io/", 503, "Unavailable", Message(), io.BytesIO(b""))
    opener, _ = _opener({"https://acme.ghost.io/": error})
    with mock.patch("urllib.request.build_opener", return_value=opener), pytest.raises(urllib.error.HTTPError):
        _fetch_site_root("https://acme.ghost.io/")


def test_a_private_site_url_is_refused_before_any_request() -> None:
    opener, requested = _opener({})
    with mock.patch("urllib.request.build_opener", return_value=opener), pytest.raises(_UnsafeSiteURL):
        _fetch_site_root("http://192.168.1.10/")

    assert requested == []

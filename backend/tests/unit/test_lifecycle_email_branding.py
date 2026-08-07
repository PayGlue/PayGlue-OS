# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-202: lifecycle emails render a plain-text body into PayGlue's branded HTML
shell, so admins keep editing plain text while the email looks designed."""
from payglue_backend.authn.lifecycle_emails import _render_branded_email


def test_render_wraps_body_in_branded_shell_and_linkifies() -> None:
    html = _render_branded_email(
        "Subject", "Hello there.\n\nVisit https://dashboard.example.com/x now."
    )
    # Branded dark shell + PayGlue wordmark.
    assert "background-color:#0f172a" in html
    assert ">Pay<" in html and ">Glue<" in html
    # Body content preserved, split into paragraphs, URL linkified.
    assert "Hello there." in html
    assert '<a href="https://dashboard.example.com/x"' in html
    # Two body paragraphs (the footer <p> uses a different colour).
    assert html.count("color:#cbd5e1") == 2


def test_render_escapes_html_in_body() -> None:
    html = _render_branded_email("S", "Tom & <b>Jerry</b>")
    assert "&amp;" in html
    assert "&lt;b&gt;" in html
    # The raw tag must not survive into the markup.
    assert "<b>Jerry" not in html

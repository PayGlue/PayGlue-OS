# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The few marks a mail body may carry, in HTML and in the text part."""
from payglue_backend.authn import mail_markup


def test_plain_text_renders_as_before() -> None:
    body = "Hi there,\nthanks for signing up.\n\nVisit https://example.com today.\n\n__\nCheers,\nPayGlue - Team"
    html = mail_markup.to_html(body)
    assert html.count("<p ") == 3
    assert "Hi there,<br />thanks for signing up." in html
    assert '<a href="https://example.com" ' in html
    assert "__<br />Cheers,<br />PayGlue - Team" in html
    assert mail_markup.to_text(body) == body


def test_headings_lists_bold_and_links() -> None:
    body = "## What changed\n\n- **Faster** sync\n- A [new guide](https://example.com/guide)\n\n1. One\n2. Two"
    html = mail_markup.to_html(body)
    assert "<h2 " in html and ">What changed</h2>" in html
    assert "<ul " in html and "<li><strong>Faster</strong> sync</li>" in html
    assert '<a href="https://example.com/guide" style="' in html and ">new guide</a>" in html
    assert "<ol " in html and "<li>Two</li>" in html
    assert mail_markup.to_text(body) == (
        "What changed\n\n- Faster sync\n- A new guide (https://example.com/guide)\n\n1. One\n2. Two"
    )


def test_a_link_is_not_linked_twice() -> None:
    html = mail_markup.to_html("[docs](https://example.com/docs)")
    assert html.count("<a ") == 1


def test_markup_in_the_body_is_escaped() -> None:
    html = mail_markup.to_html('<script>alert(1)</script> [x](javascript:alert(1)) [y](https://e.com/"onmouseover=1)')
    assert "<script>" not in html
    assert 'href="javascript' not in html
    assert '"onmouseover' not in html


def test_markers_and_addresses_stay_text() -> None:
    body = "Fill [[DATE]] in.\nWrite to some_name@example.com or open file_name.txt."
    assert mail_markup.to_html(body).count("<a ") == 0
    assert "[[DATE]]" in mail_markup.to_html(body)
    assert mail_markup.to_text(body) == body

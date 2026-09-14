# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-320 / PG-321: the embedded pricing table script and the paywall overlay
must both know the price fallback and the cross icon. The scripts are strings
in views.py, so this is a guard against one of them being edited without the
other; the behaviour itself is checked with node in the PR (see the ticket)."""
from payglue_backend.webhooks import views


def test_pricing_table_script_has_the_fallback_and_the_cross() -> None:
    js = views._PRICING_TABLE_JS
    assert "function priceFor(t,showToggle,yearly)" in js
    assert "var pf=priceFor(t,showToggle,yearly);" in js
    assert "if(i==='cross')" in js and "&#10005;" in js
    # PG-322: the button follows the toggle when the tier has a yearly product.
    assert "var ctaUrl=(showToggle&&yearly&&t.cta_url_yearly)?t.cta_url_yearly:(t.cta_url||'');" in js


def test_paywall_overlay_has_the_fallback_and_the_icon_map() -> None:
    js = views._PAYWALL_JS
    assert "var price=_preferY?(_y||_m):(_m||_y);" in js
    assert "cross:'\\u2715 '" in js
    assert "var _ctaUrl=(!!tbl.show_toggle&&isYearly&&tier.cta_url_yearly)?tier.cta_url_yearly:(tier.cta_url||tier.cta_url_yearly);" in js
    # The old line rendered every feature with a check mark, whatever its icon.
    assert "li.textContent='✓ '+" not in js


def test_paywall_card_applies_alignment_text_colour_radius_and_width() -> None:
    """PG-324: the editor saved these four for weeks and the card ignored them."""
    js = views._PAYWALL_JS
    assert "var align=(cfg.alignment==='center'||cfg.alignment==='right')?cfg.alignment:'left';" in js
    assert "text-align:'+align+';'" in js
    assert "var textColor=cfg.text_color||'#fff';" in js
    assert "var radius=cfg.border_radius==='none'?'0':(cfg.border_radius==='full'?'9999px':'0.4em');" in js
    assert "var fullWidth=cfg.width==='full';" in js

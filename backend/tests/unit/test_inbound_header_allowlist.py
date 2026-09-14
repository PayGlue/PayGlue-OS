# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The inbound view keeps only allowlisted headers for the queue, and the
adapters verify from that snapshot. A header an adapter reads but the view does
not keep fails every delivery of that provider, and no adapter test notices,
because adapter tests hand the headers over directly (PG-318).

This test reads the adapter sources instead of trusting anyone to remember the
list: every header name an adapter compares against or looks up has to be in
the allowlist. Headers that are read and never verified would also be caught,
which is fine; the cost of one extra entry is nothing next to a silent outage.
"""

import pathlib
import re

from payglue_backend.webhooks.views import WebhookIngestView

ADAPTERS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src/payglue_backend/webhooks/adapters"
)

# `key.lower() == "creem-signature"`, `h.get("paypal-cert-url")`,
# `_SIGNATURE_HEADER = "x-patreon-signature"`, `_EVENT_HEADER = "x-patreon-event"`
_PATTERNS = [
    re.compile(r'key\.lower\(\)\s*==\s*"([a-z0-9-]+)"'),
    re.compile(r'\bh\.get\("([a-z0-9-]+)"\)'),
    re.compile(r'_(?:SIGNATURE|EVENT)_HEADER\s*=\s*"([A-Za-z0-9-]+)"'),
]


def headers_read_by_adapters() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(ADAPTERS.glob("*.py")):
        if path.name.startswith("_"):
            continue
        source = path.read_text(encoding="utf-8")
        names = {
            m.group(1).lower()
            for pattern in _PATTERNS
            for m in pattern.finditer(source)
        }
        if names:
            found[path.stem] = names
    return found


def test_the_scan_finds_the_headers_it_is_meant_to_find() -> None:
    """Guards the guard: if the adapters change how they read headers, this
    fails first, instead of the main test passing on an empty set."""
    found = headers_read_by_adapters()
    assert "creem-signature" in found["creem"]
    assert "x-patreon-event" in found["patreon"]
    assert "paypal-transmission-sig" in found["paypal"]


def test_every_header_an_adapter_reads_survives_the_queue() -> None:
    allowlist = {name.lower() for name in WebhookIngestView._HEADER_ALLOWLIST}
    missing = {
        adapter: sorted(names - allowlist)
        for adapter, names in headers_read_by_adapters().items()
        if names - allowlist
    }
    assert missing == {}, (
        f"headers read by adapters but dropped by the inbound view: {missing}"
    )

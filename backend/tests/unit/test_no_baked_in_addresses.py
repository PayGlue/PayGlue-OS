"""No address of ours survives in a default (PG-239).

The rule these pin is the same one PG-238 established for URLs: an installation
that configures nothing must end up with *nothing*, never with something
belonging to whoever wrote the code. The failure mode is not theoretical. Every
one of these defaults shipped in the public repository, so a self-hosted
install sent mail from our domain, addressed its internal notices to our inbox,
and accepted Host headers for four of our hostnames.
"""

import re
from pathlib import Path

from django.conf import settings

import payglue_backend.config.settings as settings_module

SETTINGS_SOURCE = Path(settings_module.__file__).read_text(encoding="utf-8")

# Matches an address or bare host on a domain we own, in either spelling.
OURS = re.compile(r"[\w.+-]*@?(payglue|ghostglue|ghost-glue)\.(io|com|de)", re.IGNORECASE)


class TestMailDefaults:
    def test_internal_notices_have_no_default_recipient(self) -> None:
        # Empty is the whole point: these notices carry customer email
        # addresses, and a default would mail one installation's customer data
        # to whoever owns that address.
        assert "INTERNAL_ADMIN_EMAIL" in SETTINGS_SOURCE
        assert 'os.environ.get("INTERNAL_ADMIN_EMAIL", "")' in SETTINGS_SOURCE

    def test_the_sender_default_is_not_a_domain_we_own(self) -> None:
        default = _default_for("DEFAULT_FROM_EMAIL")
        assert not OURS.search(default), default

    def test_system_notices_reuse_the_configured_sender(self) -> None:
        # Rather than carrying a second literal that has to be kept in step.
        assert settings.SYSTEM_NOTICE_FROM_EMAIL == settings.DEFAULT_FROM_EMAIL


class TestHostDefaults:
    def test_allowed_hosts_default_is_loopback_only(self) -> None:
        default = _default_for("DJANGO_ALLOWED_HOSTS")
        assert not OURS.search(default), default
        assert set(default.split(",")) <= {"localhost", "127.0.0.1", "0.0.0.0"}


def test_no_address_of_ours_is_hardcoded_anywhere_in_settings() -> None:
    """The catch-all. A new setting added later trips this without anyone
    having to remember to write a test for it."""
    offenders = [
        line.strip()
        for line in SETTINGS_SOURCE.splitlines()
        # Comments explain *why* a value is gone, so they may name us.
        if not line.strip().startswith("#") and OURS.search(line)
    ]
    assert offenders == [], offenders


def _default_for(name: str) -> str:
    """The literal fallback passed to os.environ.get for `name`.

    Read out of the source rather than the live setting, because the live
    setting reflects whatever the test environment happens to export, which is
    exactly not what is being checked here.
    """
    match = re.search(
        rf'os\.environ\.get\(\s*"{name}",\s*(?:#[^\n]*\n\s*)*"([^"]*)"',
        SETTINGS_SOURCE,
    )
    assert match is not None, f"no literal default found for {name}"
    return match.group(1)

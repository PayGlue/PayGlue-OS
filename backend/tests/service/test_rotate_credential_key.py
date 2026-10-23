# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Changing CREDENTIAL_ENCRYPTION_KEY without losing stored credentials."""
import base64
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from payglue_backend.tenants.models import NewsletterRouting
from payglue_backend.webhooks.credentials import FernetCipher
from payglue_backend.webhooks.models import TenantProviderCredential

pytestmark = pytest.mark.django_db

OLD = base64.urlsafe_b64encode(b"o" * 32).decode("ascii")
NEW = base64.urlsafe_b64encode(b"n" * 32).decode("ascii")
STRANGER = base64.urlsafe_b64encode(b"s" * 32).decode("ascii")


def _store_with(key: str) -> tuple[TenantProviderCredential, NewsletterRouting]:
    cipher = FernetCipher(key, previous_keys=[])
    credential = TenantProviderCredential.objects.create(
        tenant_slug="tenant-a", provider_key="polar", credentials_enc=cipher.encrypt('{"api_key": "pk"}')
    )
    routing = NewsletterRouting.objects.create(
        ghost_api_base_url="https://blog.example.com", ghost_admin_api_key_enc=cipher.encrypt("id:secret")
    )
    return credential, routing


def _run(*args: str) -> str:
    out = StringIO()
    call_command("rotate_credential_key", *args, stdout=out)
    return out.getvalue()


@override_settings(CREDENTIAL_ENCRYPTION_KEY=NEW, CREDENTIAL_ENCRYPTION_KEY_PREVIOUS=[OLD])
def test_dry_run_reports_and_changes_nothing() -> None:
    credential, routing = _store_with(OLD)

    output = _run()

    assert "2 value(s) to re-encrypt" in output
    credential.refresh_from_db()
    routing.refresh_from_db()
    assert not FernetCipher().is_current(credential.credentials_enc)
    assert not FernetCipher().is_current(routing.ghost_admin_api_key_enc)


@override_settings(CREDENTIAL_ENCRYPTION_KEY=NEW, CREDENTIAL_ENCRYPTION_KEY_PREVIOUS=[OLD])
def test_apply_moves_everything_to_the_new_key_and_keeps_the_content() -> None:
    credential, routing = _store_with(OLD)
    updated_at = credential.updated_at

    output = _run("--apply")

    assert "Re-encrypted 2 value(s)" in output
    credential.refresh_from_db()
    routing.refresh_from_db()
    new_only = FernetCipher(NEW, previous_keys=[])
    assert new_only.decrypt(credential.credentials_enc) == '{"api_key": "pk"}'
    assert new_only.decrypt(routing.ghost_admin_api_key_enc) == "id:secret"
    assert credential.updated_at == updated_at
    assert "pk" not in output and "secret" not in output


@override_settings(CREDENTIAL_ENCRYPTION_KEY=NEW, CREDENTIAL_ENCRYPTION_KEY_PREVIOUS=[OLD])
def test_a_second_run_has_nothing_left_to_do() -> None:
    _store_with(OLD)
    _run("--apply")

    assert "0 value(s) to re-encrypt" in _run("--apply")


@override_settings(CREDENTIAL_ENCRYPTION_KEY=NEW, CREDENTIAL_ENCRYPTION_KEY_PREVIOUS=[OLD])
def test_one_unreadable_value_stops_the_run_before_anything_is_written() -> None:
    credential, _ = _store_with(OLD)
    foreign = TenantProviderCredential.objects.create(
        tenant_slug="tenant-b",
        provider_key="paddle",
        credentials_enc=FernetCipher(STRANGER, previous_keys=[]).encrypt("{}"),
    )

    with pytest.raises(CommandError, match=f"id={foreign.pk}"):
        _run("--apply")

    credential.refresh_from_db()
    assert not FernetCipher().is_current(credential.credentials_enc)

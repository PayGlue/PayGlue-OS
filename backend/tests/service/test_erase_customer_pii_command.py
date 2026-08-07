# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-198 (GDPR Art. 17): erase_customer_pii scrubs a single end-customer's
PII from webhook event logs, matched by email, in place (row survives, PII
fields nulled), scoped optionally by tenant, no-op under --dry-run."""
import pytest
from django.core.management import call_command

from payglue_backend.webhooks.models import WebhookInboundEvent

pytestmark = pytest.mark.django_db


def _event(tenant_slug: str, email: str, snapshot: dict | None = None) -> WebhookInboundEvent:
    return WebhookInboundEvent.objects.create(
        tenant_slug=tenant_slug,
        provider="creem",
        status=WebhookInboundEvent.Status.PROCESSED,
        payload_raw=f'{{"customer":{{"email":"{email}"}}}}'.encode(),
        payload_snapshot=snapshot,
        last_error="",
        endpoint_path="/webhooks/creem",
    )


def test_scrubs_matching_rows_in_place() -> None:
    hit = _event("acme", "jane@customer.com")
    call_command("erase_customer_pii", "--email", "jane@customer.com")

    hit.refresh_from_db()
    # Row survives, PII fields are emptied.
    assert WebhookInboundEvent.objects.filter(pk=hit.pk).exists()
    assert bytes(hit.payload_raw) == b""
    assert hit.payload_snapshot is None
    assert hit.endpoint_metadata["pii_erased"] is True
    assert "pii_erased_at" in hit.endpoint_metadata


def test_match_is_case_insensitive() -> None:
    hit = _event("acme", "Jane@Customer.com")
    call_command("erase_customer_pii", "--email", "jane@CUSTOMER.com")

    hit.refresh_from_db()
    assert bytes(hit.payload_raw) == b""


def test_matches_email_in_snapshot_only() -> None:
    # Raw payload doesn't contain the email, but the parsed snapshot does.
    hit = WebhookInboundEvent.objects.create(
        tenant_slug="acme",
        provider="creem",
        status=WebhookInboundEvent.Status.PROCESSED,
        payload_raw=b"opaque-encrypted-blob",
        payload_snapshot={"data": {"buyer_email": "hidden@customer.com"}},
        endpoint_path="/webhooks/creem",
    )
    call_command("erase_customer_pii", "--email", "hidden@customer.com")

    hit.refresh_from_db()
    assert hit.payload_snapshot is None
    assert hit.endpoint_metadata["pii_erased"] is True


def test_leaves_non_matching_rows_untouched() -> None:
    other = _event("acme", "someone-else@customer.com")
    call_command("erase_customer_pii", "--email", "jane@customer.com")

    other.refresh_from_db()
    assert bytes(other.payload_raw) != b""
    assert other.payload_snapshot is None or "pii_erased" not in other.endpoint_metadata
    assert "pii_erased" not in other.endpoint_metadata


def test_tenant_scope_bounds_the_scrub() -> None:
    same_email_other_tenant = _event("beta", "jane@customer.com")
    in_scope = _event("acme", "jane@customer.com")
    call_command("erase_customer_pii", "--email", "jane@customer.com", "--tenant", "acme")

    in_scope.refresh_from_db()
    same_email_other_tenant.refresh_from_db()
    assert bytes(in_scope.payload_raw) == b""
    # Another tenant's identically-addressed customer is not touched.
    assert bytes(same_email_other_tenant.payload_raw) != b""


def test_dry_run_changes_nothing() -> None:
    hit = _event("acme", "jane@customer.com")
    call_command("erase_customer_pii", "--email", "jane@customer.com", "--dry-run")

    hit.refresh_from_db()
    assert bytes(hit.payload_raw) != b""
    assert "pii_erased" not in hit.endpoint_metadata


def test_empty_email_is_rejected() -> None:
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("erase_customer_pii", "--email", "   ")

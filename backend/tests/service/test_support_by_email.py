# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Support requests handled by email.

The default path: the request is stored, the customer gets a confirmation and
the address in INTERNAL_ADMIN_EMAIL gets a copy. A support request is somebody
asking for help, so a broken mailer must not take the request down with it.
"""
from unittest import mock

import pytest

from payglue_backend.tenants import support
from payglue_backend.tenants.models import SupportRequest, Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(schema_name="acme", slug="acme")


# override_settings rather than assigning to `settings`, so the test does not
# read like a dependency on a setting every installation defines.
@pytest.fixture
def by_email():
    from django.test import override_settings

    with override_settings(SUPPORT_FORWARDER=""):
        yield


def _create(tenant: Tenant, **overrides) -> SupportRequest:
    kwargs = {
        "tenant": tenant,
        "email": "reader@example.com",
        "name": "Sam",
        "topic": "billing",
        "message": "My invoice has the wrong VAT number.",
    }
    kwargs.update(overrides)
    return support.create_support_request(**kwargs)


def _pin(tenant: Tenant, *, code="PGS-12345", hours=24):
    from datetime import timedelta

    from django.utils import timezone

    from payglue_backend.tenants.models import ServicePin

    return ServicePin.objects.create(
        tenant=tenant, code=code, expires_at=timezone.now() + timedelta(hours=hours)
    )


def test_by_email_nothing_else_is_attempted(tenant: Tenant, by_email) -> None:
    """Email is a complete way to handle support, not a degraded one."""
    with mock.patch("urllib.request.urlopen") as urlopen:
        request = _create(tenant)

    urlopen.assert_not_called()
    assert request.reference == f"PG-REQ-{request.pk}"


def test_the_customer_and_we_both_get_an_email(
    tenant: Tenant, by_email, settings
) -> None:
    from django.core import mail

    # Our half of the pair goes to INTERNAL_ADMIN_EMAIL, which has no default
    # any more (PG-239). Without an address configured only the customer's
    # copy goes out, which is the point of the setting, not a failure.
    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    request = _create(tenant)

    recipients = {addr for m in mail.outbox for addr in m.to}
    assert "reader@example.com" in recipients
    assert len(mail.outbox) == 2
    customer_mail = next(m for m in mail.outbox if "reader@example.com" in m.to)
    assert request.reference in customer_mail.subject


def test_without_an_admin_address_only_the_customer_is_written_to(
    tenant: Tenant, by_email, settings
) -> None:
    """An installation that configures no admin address gets no admin notice,
    and nothing else changes. The customer still gets their confirmation, and
    the request is still stored, because the notice is a courtesy to whoever
    runs the place and not part of handling the request (PG-239)."""
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = ""
    _create(tenant)

    assert [m.to for m in mail.outbox] == [["reader@example.com"]]
    assert SupportRequest.objects.count() == 1


def test_our_own_notification_replies_to_the_customer(
    tenant: Tenant, by_email, settings
) -> None:
    """Our alert goes from team@ to team@, so without a Reply-To, hitting Reply
    in a mail client answers ourselves instead of the person who wrote in."""
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    _create(tenant)

    ours = next(m for m in mail.outbox if "ops@example.com" in m.to)
    assert ours.reply_to == ["Sam <reader@example.com>"]


def test_a_nameless_request_still_gets_a_usable_reply_to(
    tenant: Tenant, by_email, settings
) -> None:
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    _create(tenant, name="")

    ours = next(m for m in mail.outbox if "ops@example.com" in m.to)
    assert ours.reply_to == ["reader@example.com"]


def test_a_failing_mailer_does_not_lose_the_request(tenant: Tenant, by_email) -> None:
    with mock.patch.object(support, "_send_branded", side_effect=RuntimeError("resend down")):
        request = _create(tenant)

    assert SupportRequest.objects.filter(pk=request.pk).exists()


def test_the_confirmation_goes_where_the_customer_asked(tenant: Tenant, by_email) -> None:
    """The address in the form used to be overruled by the signed-in one, so
    changing it did nothing at all."""
    from django.core import mail

    _create(tenant, email="elsewhere@example.com", account_email="signed-in@example.com")

    assert ["elsewhere@example.com"] in [m.to for m in mail.outbox]




def test_the_pin_never_reaches_the_customer(tenant: Tenant, by_email, settings) -> None:
    """A consent code has no business sitting in a mailbox longer than it must,
    and the customer can read it in the dashboard anyway."""
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    _pin(tenant, code="PGS-99999")
    _create(tenant)

    to_customer = next(m for m in mail.outbox if "reader@example.com" in m.to)
    assert "PGS-99999" not in to_customer.body
    to_us = next(m for m in mail.outbox if "ops@example.com" in m.to)
    assert "PGS-99999" in to_us.body


def test_by_email_statuses_stay_as_they_are(tenant: Tenant, by_email) -> None:
    request = _create(tenant)

    assert support.sync_statuses([request]) == [request]
    request.refresh_from_db()
    assert request.status == SupportRequest.STATUS_OPEN


def test_a_forwarder_that_cannot_be_imported_falls_back_to_email(tenant: Tenant) -> None:
    from django.core import mail
    from django.test import override_settings

    with override_settings(SUPPORT_FORWARDER="payglue_backend.does_not_exist", INTERNAL_ADMIN_EMAIL="ops@example.com"):
        request = _create(tenant)

    assert request.reference == f"PG-REQ-{request.pk}"
    assert len(mail.outbox) == 2

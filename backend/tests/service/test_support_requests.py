# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Support requests, and their one-way mirror into the helpdesk.

The tests that matter here are the failure ones. A support request is somebody
asking for help, so the whole design rests on the helpdesk being allowed to
fail without taking the request down with it.
"""
from unittest import mock

import pytest

from payglue_backend.tenants import helpdesk, support
from payglue_backend.tenants.models import SupportRequest, Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(schema_name="acme", slug="acme")


# override_settings rather than assigning to `settings`: the published tree
# does not define these two, and an assignment reads like a dependency on them.
@pytest.fixture
def helpdesk_on(settings):
    from django.test import override_settings

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    with override_settings(FEEDBACKOS_URL="https://hub.example.com", FEEDBACKOS_API_KEY="test-key"):
        yield


@pytest.fixture
def helpdesk_off():
    from django.test import override_settings

    with override_settings(FEEDBACKOS_URL="", FEEDBACKOS_API_KEY=""):
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


def _filed(tenant: Tenant, ticket=("ticket_abc", "#2"), **overrides):
    """Create a request through the helpdesk and return it with the call."""
    with mock.patch.object(helpdesk, "create_support_ticket", return_value=ticket) as filed:
        request = _create(tenant, **overrides)
    return request, filed.call_args.kwargs


# --- with a helpdesk --------------------------------------------------------


def test_with_a_helpdesk_the_request_becomes_a_ticket_and_we_send_no_mail(
    tenant: Tenant, helpdesk_on
) -> None:
    """The helpdesk confirms and answers; a mail from here would be the
    customer's second confirmation for the same request."""
    from django.core import mail

    request, kwargs = _filed(tenant)

    assert request.tracker_issue_id == "ticket_abc"
    assert request.reference == "#2"
    assert mail.outbox == []
    assert kwargs["topic"] == "billing"
    assert kwargs["email"] == "reader@example.com"
    # The message goes in as written; team-only context goes into the note.
    assert kwargs["message"] == "My invoice has the wrong VAT number."
    assert "Service PIN" in kwargs["internal_note"]


def test_a_helpdesk_that_cannot_be_reached_falls_back_to_email(
    tenant: Tenant, helpdesk_on
) -> None:
    """The whole point of writing the row first. Losing somebody's question
    because a third-party API timed out would be the worst outcome here."""
    from django.core import mail

    request, _ = _filed(tenant, ticket=None)

    assert SupportRequest.objects.count() == 1
    assert request.tracker_identifier == ""
    # They still get a reference, just ours rather than the helpdesk's.
    assert request.reference == f"PG-REQ-{request.pk}"
    assert len(mail.outbox) == 2


# --- without a helpdesk -----------------------------------------------------


def test_without_a_helpdesk_nothing_is_attempted(tenant: Tenant, helpdesk_off) -> None:
    """A self-hosted install with no helpdesk is a normal install, not a
    broken one. Support has to keep working without it."""
    with mock.patch("urllib.request.urlopen") as urlopen:
        request = _create(tenant)

    urlopen.assert_not_called()
    assert request.reference == f"PG-REQ-{request.pk}"


def test_the_customer_and_we_both_get_an_email(
    tenant: Tenant, helpdesk_off, settings
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
    tenant: Tenant, helpdesk_off, settings
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
    tenant: Tenant, helpdesk_off, settings
) -> None:
    """Our alert goes from team@ to team@, so without a Reply-To, hitting Reply
    in a mail client answers ourselves instead of the person who wrote in."""
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    _create(tenant)

    ours = next(m for m in mail.outbox if "ops@example.com" in m.to)
    assert ours.reply_to == ["Sam <reader@example.com>"]


def test_a_nameless_request_still_gets_a_usable_reply_to(
    tenant: Tenant, helpdesk_off, settings
) -> None:
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    _create(tenant, name="")

    ours = next(m for m in mail.outbox if "ops@example.com" in m.to)
    assert ours.reply_to == ["reader@example.com"]


def test_a_failing_mailer_does_not_lose_the_request(tenant: Tenant, helpdesk_off) -> None:
    with mock.patch.object(support, "_send_branded", side_effect=RuntimeError("resend down")):
        request = _create(tenant)

    assert SupportRequest.objects.filter(pk=request.pk).exists()


def test_the_confirmation_goes_where_the_customer_asked(tenant: Tenant, helpdesk_off) -> None:
    """The address in the form used to be overruled by the signed-in one, so
    changing it did nothing at all."""
    from django.core import mail

    _create(tenant, email="elsewhere@example.com", account_email="signed-in@example.com")

    assert ["elsewhere@example.com"] in [m.to for m in mail.outbox]


# --- status sync ----------------------------------------------------------


def test_status_follows_the_helpdesk_without_a_mail_from_here(
    tenant: Tenant, helpdesk_on
) -> None:
    """The helpdesk mails its own status changes; a second mail from here
    would tell the customer the same thing twice."""
    from django.core import mail

    request, _ = _filed(tenant)
    with mock.patch.object(
        helpdesk, "fetch_statuses", return_value={"ticket_abc": SupportRequest.STATUS_DONE}
    ):
        support.sync_statuses([request])

    request.refresh_from_db()
    assert request.status == SupportRequest.STATUS_DONE
    assert request.status_synced_at is not None
    assert mail.outbox == []


def test_a_resolved_request_is_never_reopened(tenant: Tenant, helpdesk_on) -> None:
    """We reopen tickets for our own bookkeeping. A customer who was
    told their question was answered should not watch it flip back."""
    request, _ = _filed(tenant)
    request.status = SupportRequest.STATUS_DONE
    request.save(update_fields=["status"])

    with mock.patch.object(helpdesk, "fetch_statuses") as fetch:
        support.sync_statuses([request])

    fetch.assert_not_called()


def test_an_unreachable_helpdesk_leaves_the_last_status(tenant: Tenant, helpdesk_on) -> None:
    request, _ = _filed(tenant)

    with mock.patch.object(helpdesk, "fetch_statuses", return_value={}):
        support.sync_statuses([request])

    request.refresh_from_db()
    assert request.status == SupportRequest.STATUS_OPEN


def test_requests_without_a_ticket_are_not_asked_about(tenant: Tenant, helpdesk_off) -> None:
    request = _create(tenant)

    with mock.patch.object(helpdesk, "fetch_statuses") as fetch:
        support.sync_statuses([request])

    fetch.assert_not_called()


def test_requests_from_the_old_tracker_keep_their_status(tenant: Tenant) -> None:
    """Filed before the helpdesk, with an id the helpdesk does not know. That
    tracker is gone, so asking anybody about them would only produce errors."""
    request = SupportRequest.objects.create(
        tenant=tenant,
        email="reader@example.com",
        message="Old one.",
        tracker_issue_id="iss_1",
        tracker_identifier="PGSUP-12",
    )

    with mock.patch.object(helpdesk, "fetch_statuses") as fetch:
        support.sync_statuses([request])

    fetch.assert_not_called()
    request.refresh_from_db()
    assert request.status == SupportRequest.STATUS_OPEN


# --- what the customer can see -------------------------------------------


def test_the_serializer_never_exposes_the_ticket(tenant: Tenant, helpdesk_on) -> None:
    """Internal notes live on that ticket. Leaking the id is the first step
    towards leaking them, so it is not in the payload at all."""
    from payglue_backend.tenants.serializers import SupportRequestSerializer

    request, _ = _filed(tenant)

    data = SupportRequestSerializer(request).data
    assert "tracker_issue_id" not in data
    assert "message" not in data
    assert data["reference"] == "#2"
    assert data["status"] == "open"


# --- the ticket title -------------------------------------------------------


def test_the_title_does_not_swallow_the_second_paragraph(tenant: Tenant, helpdesk_on) -> None:
    """Cutting the raw message at 80 characters pulled the line break into the
    title, so the start of paragraph two looked like a heading. Found on the
    first real request through the live path."""
    _, kwargs = _filed(
        tenant,
        message="Testlauf, bitte ignorieren. Umlaute: aeoeue ss, und ein <b>Tag</b>.\n\nZweiter Absatz nach einer Leerzeile.",
    )

    title = kwargs["title"]
    assert "\n" not in title
    assert "Zweiter" not in title
    assert title == "Testlauf, bitte ignorieren. Umlaute: aeoeue ss, und ein <b>Tag</b>."


def test_a_short_message_keeps_its_whole_title(tenant: Tenant, helpdesk_on) -> None:
    _, kwargs = _filed(tenant, message="Kurze Frage zu Polar.")

    assert kwargs["title"] == "Kurze Frage zu Polar."


def test_the_cut_lands_between_words(tenant: Tenant, helpdesk_on) -> None:
    _, kwargs = _filed(tenant, message="wort " * 40)

    assert "wor..." not in kwargs["title"]
    assert kwargs["title"].endswith("wort...")


def test_the_subject_becomes_the_ticket_title(tenant: Tenant, helpdesk_on) -> None:
    _, kwargs = _filed(
        tenant, subject="Paywall zeigt nichts nach dem Kauf", message="Langer Text, egal was."
    )

    assert kwargs["title"] == "Paywall zeigt nichts nach dem Kauf"


# --- who wrote, and what we may do ----------------------------------------


@pytest.fixture
def owner(tenant: Tenant):
    """A workspace with an owner, which is the agency case in miniature."""
    from payglue_backend.tenants.models import TenantMembership, UserProfile

    # firebase_uid is the legacy name for the auth subject, kept on purpose.
    profile = UserProfile.objects.create(email="owner@example.com", firebase_uid="uid-owner")
    TenantMembership.objects.create(
        tenant=tenant, user_profile=profile, role=TenantMembership.Role.OWNER
    )
    return profile


def _pin(tenant: Tenant, *, code="PGS-12345", hours=24, revoked=False):
    from datetime import timedelta

    from django.utils import timezone

    from payglue_backend.tenants.models import ServicePin

    return ServicePin.objects.create(
        tenant=tenant,
        code=code,
        expires_at=timezone.now() + timedelta(hours=hours),
        revoked_at=timezone.now() if revoked else None,
    )


def test_the_note_names_the_publication(tenant: Tenant, helpdesk_on) -> None:
    _, kwargs = _filed(tenant)

    assert "Publication: acme" in kwargs["internal_note"]


def test_a_different_signing_address_is_named(tenant: Tenant, helpdesk_on) -> None:
    _, kwargs = _filed(tenant, email="wrote@example.com", account_email="signed-in@example.com")

    assert "Submitted by: signed-in@example.com" in kwargs["internal_note"]


def test_the_same_address_is_not_repeated(tenant: Tenant, helpdesk_on) -> None:
    """The normal case. Printing one address twice is noise, and a difference
    is the only thing worth looking at."""
    _, kwargs = _filed(tenant, email="same@example.com", account_email="SAME@example.com")

    assert "Submitted by:" not in kwargs["internal_note"]


def test_the_owner_is_named_when_somebody_else_writes(
    tenant: Tenant, owner, helpdesk_on
) -> None:
    _, kwargs = _filed(tenant, email="staff@agency.example", account_email="staff@agency.example")

    assert "Account owner: owner@example.com" in kwargs["internal_note"]


def test_the_owner_is_not_repeated_when_they_write_themselves(
    tenant: Tenant, owner, helpdesk_on
) -> None:
    _, kwargs = _filed(tenant, email="owner@example.com", account_email="owner@example.com")

    assert "Account owner:" not in kwargs["internal_note"]


def test_a_valid_pin_reaches_the_note(tenant: Tenant, helpdesk_on) -> None:
    _pin(tenant)
    _, kwargs = _filed(tenant)

    assert "PGS-12345" in kwargs["internal_note"]
    assert "active changes authorised" in kwargs["internal_note"]


def test_without_a_pin_the_note_says_so(tenant: Tenant, helpdesk_on) -> None:
    """The more important of the two lines: it tells whoever picks the ticket
    up that they may look and not touch."""
    _, kwargs = _filed(tenant)

    assert "read and debug only" in kwargs["internal_note"]


def test_a_revoked_pin_does_not_count(tenant: Tenant, helpdesk_on) -> None:
    _pin(tenant, revoked=True)
    _, kwargs = _filed(tenant)

    assert "read and debug only" in kwargs["internal_note"]


def test_an_expired_pin_does_not_count(tenant: Tenant, helpdesk_on) -> None:
    _pin(tenant, hours=-1)
    _, kwargs = _filed(tenant)

    assert "read and debug only" in kwargs["internal_note"]


def test_the_pin_never_reaches_the_customer(tenant: Tenant, helpdesk_off, settings) -> None:
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


def test_the_pin_stays_out_of_the_customers_ticket(tenant: Tenant, helpdesk_on) -> None:
    """The customer sees the ticket itself, so the PIN only goes in the note."""
    _pin(tenant, code="PGS-99999")
    _, kwargs = _filed(tenant)

    assert "PGS-99999" not in kwargs["message"]
    assert "PGS-99999" not in kwargs["title"]
    assert "PGS-99999" in kwargs["internal_note"]

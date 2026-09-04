# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Support requests, and their one-way mirror into the issue tracker.

The tests that matter here are the failure ones. A support request is somebody
asking for help, so the whole design rests on the tracker being allowed to fail
without taking the request down with it.
"""
from unittest import mock

import pytest

from payglue_backend.tenants import support, tracker
from payglue_backend.tenants.models import SupportRequest, Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(schema_name="acme", slug="acme")


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


# --- filing ---------------------------------------------------------------


def test_a_request_is_stored_and_filed(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)

    assert request.tracker_identifier == "PG-231"
    assert request.reference == "PG-231"
    assert request.status == SupportRequest.STATUS_OPEN


def test_the_tracker_being_down_still_keeps_the_request(tenant: Tenant) -> None:
    """The whole point of writing the row first. Losing somebody's question
    because a third-party API timed out would be the worst outcome here."""
    with mock.patch.object(tracker, "create_support_issue", return_value=None):
        request = _create(tenant)

    assert SupportRequest.objects.count() == 1
    assert request.tracker_identifier == ""
    # They still get a reference, just ours rather than the tracker's.
    assert request.reference == f"PG-REQ-{request.pk}"


def test_the_customer_and_we_both_get_an_email(tenant: Tenant, settings) -> None:
    from django.core import mail

    # Our half of the pair goes to INTERNAL_ADMIN_EMAIL, which has no default
    # any more (PG-239). Without an address configured only the customer's
    # copy goes out, which is the point of the setting, not a failure.
    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-231")):
        _create(tenant)

    recipients = {addr for m in mail.outbox for addr in m.to}
    assert "reader@example.com" in recipients
    assert len(mail.outbox) == 2
    customer_mail = next(m for m in mail.outbox if "reader@example.com" in m.to)
    assert "PG-231" in customer_mail.subject


def test_without_an_admin_address_only_the_customer_is_written_to(
    tenant: Tenant, settings
) -> None:
    """An installation that configures no admin address gets no admin notice,
    and nothing else changes. The customer still gets their confirmation, and
    the request is still stored, because the notice is a courtesy to whoever
    runs the place and not part of handling the request (PG-239)."""
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = ""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-233")):
        _create(tenant)

    assert [m.to for m in mail.outbox] == [["reader@example.com"]]
    assert SupportRequest.objects.count() == 1


def test_our_own_notification_replies_to_the_customer(tenant: Tenant, settings) -> None:
    """Our alert goes from team@ to team@, so without a Reply-To, hitting Reply
    in a mail client answers ourselves instead of the person who wrote in."""
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-231")):
        _create(tenant)

    ours = next(m for m in mail.outbox if "ops@example.com" in m.to)
    assert ours.reply_to == ["Sam <reader@example.com>"]


def test_a_nameless_request_still_gets_a_usable_reply_to(tenant: Tenant, settings) -> None:
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-232")):
        _create(tenant, name="")

    ours = next(m for m in mail.outbox if "ops@example.com" in m.to)
    assert ours.reply_to == ["reader@example.com"]


def test_a_failing_mailer_does_not_lose_the_request(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-231")), \
         mock.patch.object(support, "_send_branded", side_effect=RuntimeError("resend down")):
        request = _create(tenant)

    assert SupportRequest.objects.filter(pk=request.pk).exists()


def test_the_issue_body_carries_who_and_where(tenant: Tenant) -> None:
    captured = {}

    def _capture(*, title, description_html, label_names=None):
        captured["title"] = title
        captured["body"] = description_html
        captured["labels"] = label_names
        return ("iss_1", "PGSUP-1")

    with mock.patch.object(tracker, "create_support_issue", _capture):
        _create(tenant)

    assert "acme" in captured["title"]
    assert "reader@example.com" in captured["body"]
    assert "<code>acme</code>" in captured["body"]
    assert "wrong VAT number" in captured["body"]


# --- status sync ----------------------------------------------------------


def test_status_follows_the_tracker(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)

    with mock.patch.object(tracker, "fetch_statuses", return_value={"iss_1": "in_progress"}):
        support.sync_statuses([request])

    request.refresh_from_db()
    assert request.status == SupportRequest.STATUS_IN_PROGRESS


def test_a_resolved_request_is_never_reopened(tenant: Tenant) -> None:
    """We reopen issues for our own bookkeeping. A customer who was
    told their question was answered should not watch it flip back."""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)
    request.status = SupportRequest.STATUS_DONE
    request.save(update_fields=["status"])

    with mock.patch.object(tracker, "fetch_statuses") as fetch:
        support.sync_statuses([request])

    fetch.assert_not_called()


def test_an_unreachable_tracker_leaves_the_last_status(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)

    with mock.patch.object(tracker, "fetch_statuses", return_value={}):
        support.sync_statuses([request])

    request.refresh_from_db()
    assert request.status == SupportRequest.STATUS_OPEN


def test_requests_without_an_issue_are_not_asked_about(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=None):
        request = _create(tenant)

    with mock.patch.object(tracker, "fetch_statuses") as fetch:
        support.sync_statuses([request])

    fetch.assert_not_called()


# --- status change notifications ------------------------------------------


def _synced_request(tenant: Tenant, new_status: str) -> "SupportRequest":
    """A request whose tracker status just moved to `new_status`, with the
    creation-time emails cleared away so tests only see the notification."""
    from django.core import mail

    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)
    mail.outbox.clear()
    with mock.patch.object(tracker, "fetch_statuses", return_value={"iss_1": new_status}):
        support.sync_statuses([request])
    return request


def test_moving_to_in_progress_emails_the_customer(tenant: Tenant, settings) -> None:
    from django.core import mail

    settings.SYSTEM_NOTICE_FROM_EMAIL = "PayGlue <noreply@example.com>"
    _synced_request(tenant, "in_progress")

    assert len(mail.outbox) == 1
    notice = mail.outbox[0]
    assert notice.to == ["reader@example.com"]
    assert notice.from_email == "PayGlue <noreply@example.com>"
    assert "PG-231" in notice.subject
    # The customer reads the same word we use in the tracker.
    assert "Active" in notice.subject


def test_closing_emails_the_closed_wording(tenant: Tenant) -> None:
    from django.core import mail

    _synced_request(tenant, "done")

    assert len(mail.outbox) == 1
    assert "Closed" in mail.outbox[0].subject
    assert "resolved" in mail.outbox[0].body


def test_an_unchanged_status_sends_nothing(tenant: Tenant) -> None:
    from django.core import mail

    _synced_request(tenant, "open")

    assert mail.outbox == []


def test_a_failing_notification_does_not_undo_the_status(tenant: Tenant) -> None:
    """The persist happens first on purpose; a mail hiccup must not leave the
    dashboard contradicting what the tracker says."""
    from django.core import mail

    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)
    mail.outbox.clear()

    with (
        mock.patch.object(tracker, "fetch_statuses", return_value={"iss_1": "in_progress"}),
        mock.patch.object(support, "_send_branded", side_effect=RuntimeError("mailer down")),
    ):
        support.sync_statuses([request])

    request.refresh_from_db()
    assert request.status == SupportRequest.STATUS_IN_PROGRESS


# --- what the customer can see -------------------------------------------


def test_the_serializer_never_exposes_the_issue(tenant: Tenant) -> None:
    """Internal comments live on that issue. Leaking the id is the first step
    towards leaking them, so it is not in the payload at all."""
    from payglue_backend.tenants.serializers import SupportRequestSerializer

    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)

    data = SupportRequestSerializer(request).data
    assert "tracker_issue_id" not in data
    assert "message" not in data
    assert data["reference"] == "PG-231"
    assert data["status"] == "open"


# --- what the issue body looks like ---------------------------------------


def test_the_message_is_escaped_before_it_becomes_an_issue(tenant: Tenant) -> None:
    """Support messages are arbitrary text from strangers, and they land in a
    page we open ourselves. A reader asking about a paywall snippet will paste
    one, so this is the normal case rather than an attack."""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-1")) as filed:
        _create(tenant, message="<script>alert(1)</script> broke my theme")

    body = filed.call_args.kwargs["description_html"]
    assert "<script>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_paragraphs_survive_the_trip(tenant: Tenant) -> None:
    """The tracker stores HTML and renders markdown literally, so line breaks
    have to be carried as markup or the whole message arrives as one block."""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-1")) as filed:
        _create(tenant, message="First thing.\n\nSecond thing.\nStill the second.")

    body = filed.call_args.kwargs["description_html"]
    assert "<p>First thing.</p>" in body
    assert "<p>Second thing.<br>Still the second.</p>" in body


# --- the client ------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_tracker_cache():
    """The project key and the state groups are memoised per process."""
    tracker._reset_cache()
    yield
    tracker._reset_cache()


@pytest.fixture
def configured(settings):
    settings.PLANE_BASE_URL = "https://tracker.example.com"
    settings.PLANE_API_KEY = "plane_api_abc"
    settings.PLANE_WORKSPACE_SLUG = "acme"
    settings.PLANE_SUPPORT_PROJECT_ID = "proj-1"
    settings.PLANE_SUPPORT_LABEL_ID = ""
    return settings


def test_nothing_is_attempted_when_the_tracker_is_not_configured(settings) -> None:
    """A self-hosted install with no tracker is a normal install, not a broken
    one. Support has to keep working without it."""
    settings.PLANE_BASE_URL = ""
    settings.PLANE_API_KEY = ""
    settings.PLANE_WORKSPACE_SLUG = ""
    settings.PLANE_SUPPORT_PROJECT_ID = ""

    with mock.patch("urllib.request.urlopen") as urlopen:
        assert tracker.create_support_issue(title="t", description_html="<p>d</p>") is None
        assert tracker.fetch_statuses(["iss_1"]) == {}

    urlopen.assert_not_called()


def test_the_identifier_is_built_from_the_project_key_and_the_number(configured) -> None:
    calls = []

    def _call(path, *, method="GET", payload=None):
        calls.append((method, path))
        if method == "POST":
            return {"id": "iss_1", "sequence_id": 12}
        return {"identifier": "PGSUP"}

    with mock.patch.object(tracker, "_call", _call):
        assert tracker.create_support_issue(title="t", description_html="<p>d</p>") == ("iss_1", "PGSUP-12")

    assert ("POST", "issues/") in calls


def test_an_issue_without_a_readable_project_key_still_returns_its_id(configured) -> None:
    """The issue exists either way. Losing the id because the second call
    failed would strand a real ticket, so only the pretty reference is lost."""
    def _call(path, *, method="GET", payload=None):
        return {"id": "iss_1", "sequence_id": 12} if method == "POST" else None

    with mock.patch.object(tracker, "_call", _call):
        assert tracker.create_support_issue(title="t", description_html="<p>d</p>") == ("iss_1", "")


def test_the_label_is_only_sent_when_configured(configured) -> None:
    captured = {}

    def _call(path, *, method="GET", payload=None):
        if method == "POST":
            captured.update(payload)
        return None

    with mock.patch.object(tracker, "_call", _call):
        tracker.create_support_issue(title="t", description_html="<p>d</p>")
    assert "labels" not in captured

    configured.PLANE_SUPPORT_LABEL_ID = "label-1"
    captured.clear()
    with mock.patch.object(tracker, "_call", _call):
        tracker.create_support_issue(title="t", description_html="<p>d</p>")
    assert captured["labels"] == ["label-1"]


def test_the_issue_starts_on_the_day_it_is_filed(configured) -> None:
    from django.utils import timezone

    captured = {}

    def _call(path, *, method="GET", payload=None):
        if method == "POST":
            captured.update(payload)
        return None

    with mock.patch.object(tracker, "_call", _call):
        tracker.create_support_issue(title="t", description_html="<p>d</p>")
    assert captured["start_date"] == timezone.localdate().isoformat()


def test_states_are_mapped_by_group_and_not_by_name(configured) -> None:
    """The one that earns its keep. Our support project calls its states
    Pending, Active, Closed and Cancelled, and renaming a column there must not
    strand the dashboard. A state *named* Closed that still sits in the started
    group is work in progress, whatever the label says."""
    def _call(path, *, method="GET", payload=None):
        if path == "states/":
            return {"results": [
                {"id": "st_1", "name": "Closed", "group": "started"},
                {"id": "st_2", "name": "Pending", "group": "unstarted"},
                {"id": "st_3", "name": "Wrapped up", "group": "completed"},
            ]}
        return {"iss_1": {"state": "st_1"}, "iss_2": {"state": "st_2"}, "iss_3": {"state": "st_3"}}[
            path.split("/")[1]
        ]

    with mock.patch.object(tracker, "_call", _call):
        assert tracker.fetch_statuses(["iss_1", "iss_2", "iss_3"]) == {
            "iss_1": "in_progress",
            "iss_2": "open",
            "iss_3": "done",
        }


def test_an_unknown_group_is_dropped_rather_than_guessed(configured) -> None:
    def _call(path, *, method="GET", payload=None):
        if path == "states/":
            return {"results": [{"id": "st_1", "group": "invented"}]}
        return {"state": "st_1"}

    with mock.patch.object(tracker, "_call", _call):
        assert tracker.fetch_statuses(["iss_1"]) == {}


def test_a_deleted_issue_leaves_the_stored_status_alone(configured) -> None:
    """Absent from the answer means absent from the result, so the caller keeps
    what it had instead of inventing a status."""
    def _call(path, *, method="GET", payload=None):
        return {"results": [{"id": "st_1", "group": "completed"}]} if path == "states/" else None

    with mock.patch.object(tracker, "_call", _call):
        assert tracker.fetch_statuses(["iss_gone"]) == {}


def test_the_status_read_is_capped_per_run(configured) -> None:
    """One call per open request against a rate limit of about sixty a minute.
    The cap turns a runaway into a partial sync that the next run finishes."""
    reads = []

    def _call(path, *, method="GET", payload=None):
        if path == "states/":
            return {"results": [{"id": "st_1", "group": "started"}]}
        reads.append(path)
        return {"state": "st_1"}

    with mock.patch.object(tracker, "_call", _call):
        result = tracker.fetch_statuses([f"iss_{n}" for n in range(60)])

    assert len(reads) == tracker._MAX_STATUS_READS
    assert len(result) == tracker._MAX_STATUS_READS


def test_a_base_url_carrying_an_api_segment_is_repaired(configured) -> None:
    """Pasting the URL with /api already on it produces a 404 on every call and
    reads exactly like a rejected token. Cheaper to absorb than to debug."""
    configured.PLANE_BASE_URL = "https://tracker.example.com/api/"
    assert tracker._project_url("issues/") == (
        "https://tracker.example.com/api/v1/workspaces/acme/projects/proj-1/issues/"
    )


def test_the_api_key_never_reaches_the_log(configured, caplog) -> None:
    """These logs get pasted into an issue one day."""
    import urllib.error

    def _boom(*a, **kw):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)

    with mock.patch("urllib.request.urlopen", _boom):
        tracker.create_support_issue(title="t", description_html="<p>d</p>")

    assert "plane_api_abc" not in caplog.text
    assert "403" in caplog.text


def test_the_title_does_not_swallow_the_second_paragraph(tenant: Tenant) -> None:
    """Cutting the raw message at 80 characters pulled the line break into the
    title, and the tracker rendered it, so the start of paragraph two looked
    like a heading. Found on the first real request through the live path."""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-13")) as filed:
        _create(
            tenant,
            message="Testlauf, bitte ignorieren. Umlaute: aeoeue ss, und ein <b>Tag</b>.\n\nZweiter Absatz nach einer Leerzeile.",
        )

    title = filed.call_args.kwargs["title"]
    assert "\n" not in title
    # Only the opening paragraph, so nothing from paragraph two leaks in and
    # no line break survives for the tracker to render as a heading.
    assert "Zweiter" not in title
    assert title.endswith("und ein <b>Tag</b>.")


def test_a_short_message_keeps_its_whole_title(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-14")) as filed:
        _create(tenant, message="Kurze Frage zu Polar.")

    assert filed.call_args.kwargs["title"].endswith("Kurze Frage zu Polar.")


def test_the_cut_lands_between_words(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-15")) as filed:
        _create(tenant, message="wort " * 40)

    title = filed.call_args.kwargs["title"]
    assert "wor..." not in title
    assert title.endswith("wort...")


# --- the subject the customer writes --------------------------------------


def test_the_subject_becomes_the_issue_title(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-20")) as filed:
        _create(tenant, subject="Paywall zeigt nichts nach dem Kauf", message="Langer Text, egal was.")

    assert filed.call_args.kwargs["title"].endswith("Paywall zeigt nichts nach dem Kauf")


def test_without_a_subject_the_message_still_supplies_a_title(tenant: Tenant) -> None:
    """Everything filed before the field existed, and anything that slips
    through empty. Deriving is the fallback, not the rule."""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-21")) as filed:
        _create(tenant, message="Kurze Frage zu Polar.")

    assert filed.call_args.kwargs["title"].endswith("Kurze Frage zu Polar.")


def test_the_subject_is_escaped_in_the_body_too(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-22")) as filed:
        _create(tenant, subject="<img src=x onerror=1>", message="Text.")

    body = filed.call_args.kwargs["description_html"]
    assert "<img" not in body
    assert "&lt;img src=x onerror=1&gt;" in body


def test_the_topic_picks_its_label(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-23")) as filed:
        _create(tenant, topic="billing")
    assert filed.call_args.kwargs["label_names"] == ["billing"]


def test_something_else_is_labelled_general(tenant: Tenant) -> None:
    """"other" would read badly on a board, so the label is called general."""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-24")) as filed:
        _create(tenant, topic="other")
    assert filed.call_args.kwargs["label_names"] == ["general"]


def test_no_topic_still_gets_a_label(tenant: Tenant) -> None:
    """Choosing a category is optional, ending up unlabelled is not: a ticket
    without a label cannot be filtered out of the board afterwards."""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-25")) as filed:
        _create(tenant, topic="")
    assert filed.call_args.kwargs["label_names"] == ["general"]


def test_labels_resolve_by_name_and_the_fixed_one_rides_along(configured) -> None:
    """A label created in the tracker works without touching the environment.
    The fixed label from the settings is added on top, which is how staging
    marks its own tickets in a board it shares with production."""
    configured.PLANE_SUPPORT_LABEL_ID = "label-staging"
    captured = {}

    def _call(path, *, method="GET", payload=None):
        if path == "labels/":
            return {"results": [{"id": "lab-billing", "name": "Billing"}, {"id": "lab-bug", "name": "bug"}]}
        if method == "POST":
            captured.update(payload)
            return {"id": "iss_1", "sequence_id": 20}
        return {"identifier": "PGSUP"}

    with mock.patch.object(tracker, "_call", _call):
        tracker.create_support_issue(title="t", description_html="<p>d</p>", label_names=["billing"])

    # Matched case-insensitively, so "billing" finds the label named "Billing".
    assert captured["labels"] == ["lab-billing", "label-staging"]


def test_an_unknown_label_name_is_skipped_and_logged(configured, caplog) -> None:
    def _call(path, *, method="GET", payload=None):
        return {"results": []} if path == "labels/" else {"id": "iss_1", "sequence_id": 21}

    with mock.patch.object(tracker, "_call", _call):
        tracker.create_support_issue(title="t", description_html="<p>d</p>", label_names=["nope"])

    assert "no label named" in caplog.text


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


def test_the_contact_address_is_the_first_one_in_the_ticket(tenant: Tenant) -> None:
    """Where a reply goes is the first thing anybody opening the ticket needs,
    so it is the first line. Pinned by a test because the block grows: subject,
    publication, owner and PIN all want to be near the top too."""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-30")) as filed:
        _create(tenant, email="wrote@example.com", account_email="signed-in@example.com")

    body = filed.call_args.kwargs["description_html"]
    assert body.index("wrote@example.com") < body.index("signed-in@example.com")
    assert body.startswith("<p><strong>Contact:</strong>")


def test_a_different_signing_address_is_named(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-31")) as filed:
        _create(tenant, email="wrote@example.com", account_email="signed-in@example.com")

    assert "Submitted by:" in filed.call_args.kwargs["description_html"]


def test_the_same_address_is_not_repeated(tenant: Tenant) -> None:
    """The normal case. Printing one address twice is noise, and a difference
    is the only thing worth looking at."""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-32")) as filed:
        _create(tenant, email="same@example.com", account_email="SAME@example.com")

    assert "Submitted by:" not in filed.call_args.kwargs["description_html"]


def test_the_owner_is_named_when_somebody_else_writes(tenant: Tenant, owner) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-33")) as filed:
        _create(tenant, email="staff@agency.example", account_email="staff@agency.example")

    assert "owner@example.com" in filed.call_args.kwargs["description_html"]


def test_the_owner_is_not_repeated_when_they_write_themselves(tenant: Tenant, owner) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-34")) as filed:
        _create(tenant, email="owner@example.com", account_email="owner@example.com")

    assert "Account owner:" not in filed.call_args.kwargs["description_html"]


def test_a_valid_pin_reaches_the_ticket(tenant: Tenant) -> None:
    _pin(tenant)
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-35")) as filed:
        _create(tenant)

    body = filed.call_args.kwargs["description_html"]
    assert "PGS-12345" in body
    assert "active changes authorised" in body


def test_without_a_pin_the_ticket_says_so(tenant: Tenant) -> None:
    """The more important of the two lines: it tells whoever picks the ticket
    up that they may look and not touch."""
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-36")) as filed:
        _create(tenant)

    assert "read and debug only" in filed.call_args.kwargs["description_html"]


def test_a_revoked_pin_does_not_count(tenant: Tenant) -> None:
    _pin(tenant, revoked=True)
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-37")) as filed:
        _create(tenant)

    assert "read and debug only" in filed.call_args.kwargs["description_html"]


def test_an_expired_pin_does_not_count(tenant: Tenant) -> None:
    _pin(tenant, hours=-1)
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-38")) as filed:
        _create(tenant)

    assert "read and debug only" in filed.call_args.kwargs["description_html"]


def test_the_pin_never_reaches_the_customer(tenant: Tenant, settings) -> None:
    """A consent code has no business sitting in a mailbox longer than it must,
    and the customer can read it in the dashboard anyway."""
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    _pin(tenant, code="PGS-99999")
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-39")):
        _create(tenant)

    to_customer = next(m for m in mail.outbox if "reader@example.com" in m.to)
    assert "PGS-99999" not in to_customer.body
    to_us = next(m for m in mail.outbox if "ops@example.com" in m.to)
    assert "PGS-99999" in to_us.body


def test_the_confirmation_goes_where_the_customer_asked(tenant: Tenant) -> None:
    """The whole point. The address in the form used to be overruled by the
    signed-in one, so changing it did nothing at all."""
    from django.core import mail

    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-40")):
        _create(tenant, email="elsewhere@example.com", account_email="signed-in@example.com")

    assert ["elsewhere@example.com"] in [m.to for m in mail.outbox]


# --- handing the reply address to the tracker (PG-266) --------------------


def test_the_reply_address_is_handed_to_the_tracker(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-50")), \
         mock.patch.object(tracker, "link_requester_email") as link:
        _create(tenant, email="writer@example.com", name="Sam")

    link.assert_called_once_with("iss_1", email="writer@example.com", name="Sam")


def test_no_issue_means_nothing_to_link(tenant: Tenant) -> None:
    with mock.patch.object(tracker, "create_support_issue", return_value=None), \
         mock.patch.object(tracker, "link_requester_email") as link:
        _create(tenant)

    link.assert_not_called()


def test_a_failing_link_costs_the_toggle_and_nothing_else(tenant: Tenant) -> None:
    """The worst case is a ticket whose comment box cannot answer outward. The
    request itself, the emails and the reference all survive."""
    from django.core import mail

    with mock.patch.object(tracker, "create_support_issue", return_value=("iss_1", "PGSUP-51")), \
         mock.patch.object(tracker, "link_requester_email", return_value=False):
        request = _create(tenant)

    assert request.tracker_identifier == "PGSUP-51"
    assert SupportRequest.objects.filter(pk=request.pk).exists()
    assert any("reader@example.com" in m.to for m in mail.outbox)


def test_the_link_call_hits_the_work_items_path(configured) -> None:
    """There is no alias under the older issues segment, and the wrong one
    answers 404 in a way that reads like a missing issue."""
    seen = {}

    def _call(path, *, method="GET", payload=None):
        seen["path"], seen["method"], seen["payload"] = path, method, payload
        return {"id": "link-1"}

    with mock.patch.object(tracker, "_call", _call):
        assert tracker.link_requester_email("iss-1", email="a@b.de", name="Sam") is True

    assert seen["path"] == "work-items/iss-1/email-link/"
    assert seen["method"] == "POST"
    assert seen["payload"] == {"requester_email": "a@b.de", "requester_name": "Sam"}


def test_the_link_call_omits_what_the_endpoint_derives(configured) -> None:
    seen = {}

    def _call(path, *, method="GET", payload=None):
        seen.update(payload or {})
        return {}

    with mock.patch.object(tracker, "_call", _call):
        tracker.link_requester_email("iss-1", email="a@b.de")

    assert set(seen) == {"requester_email"}


def test_no_address_means_no_call(configured) -> None:
    with mock.patch.object(tracker, "_call") as call:
        assert tracker.link_requester_email("iss-1", email="") is False
        assert tracker.link_requester_email("", email="a@b.de") is False
    call.assert_not_called()

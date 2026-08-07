# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""Support requests, and their one-way mirror into Linear.

The tests that matter here are the failure ones. A support request is somebody
asking for help, so the whole design rests on Linear being allowed to fail
without taking the request down with it.
"""
from unittest import mock

import pytest

from payglue_backend.tenants import linear, support
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
    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)

    assert request.linear_identifier == "PG-231"
    assert request.reference == "PG-231"
    assert request.status == SupportRequest.STATUS_OPEN


def test_linear_being_down_still_keeps_the_request(tenant: Tenant) -> None:
    """The whole point of writing the row first. Losing somebody's question
    because a third-party API timed out would be the worst outcome here."""
    with mock.patch.object(linear, "create_support_issue", return_value=None):
        request = _create(tenant)

    assert SupportRequest.objects.count() == 1
    assert request.linear_identifier == ""
    # They still get a reference, just ours rather than Linear's.
    assert request.reference == f"PG-REQ-{request.pk}"


def test_the_customer_and_we_both_get_an_email(tenant: Tenant, settings) -> None:
    from django.core import mail

    # Our half of the pair goes to INTERNAL_ADMIN_EMAIL, which has no default
    # any more (PG-239). Without an address configured only the customer's
    # copy goes out, which is the point of the setting, not a failure.
    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-231")):
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
    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-233")):
        _create(tenant)

    assert [m.to for m in mail.outbox] == [["reader@example.com"]]
    assert SupportRequest.objects.count() == 1


def test_our_own_notification_replies_to_the_customer(tenant: Tenant, settings) -> None:
    """Our alert goes from team@ to team@, so without a Reply-To, hitting Reply
    in a mail client answers ourselves instead of the person who wrote in."""
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-231")):
        _create(tenant)

    ours = next(m for m in mail.outbox if "ops@example.com" in m.to)
    assert ours.reply_to == ["Sam <reader@example.com>"]


def test_a_nameless_request_still_gets_a_usable_reply_to(tenant: Tenant, settings) -> None:
    from django.core import mail

    settings.INTERNAL_ADMIN_EMAIL = "ops@example.com"
    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-232")):
        _create(tenant, name="")

    ours = next(m for m in mail.outbox if "ops@example.com" in m.to)
    assert ours.reply_to == ["reader@example.com"]


def test_a_failing_mailer_does_not_lose_the_request(tenant: Tenant) -> None:
    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-231")), \
         mock.patch.object(support, "_send_branded", side_effect=RuntimeError("resend down")):
        request = _create(tenant)

    assert SupportRequest.objects.filter(pk=request.pk).exists()


def test_the_issue_body_carries_who_and_where(tenant: Tenant) -> None:
    captured = {}

    def _capture(*, title, description):
        captured["title"] = title
        captured["description"] = description
        return ("iss_1", "PG-231")

    with mock.patch.object(linear, "create_support_issue", _capture):
        _create(tenant)

    assert "acme" in captured["title"]
    assert "reader@example.com" in captured["description"]
    assert "`acme`" in captured["description"]
    assert "wrong VAT number" in captured["description"]


# --- status sync ----------------------------------------------------------


def test_status_follows_linear(tenant: Tenant) -> None:
    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)

    with mock.patch.object(linear, "fetch_statuses", return_value={"iss_1": "in_progress"}):
        support.sync_statuses([request])

    request.refresh_from_db()
    assert request.status == SupportRequest.STATUS_IN_PROGRESS


def test_a_resolved_request_is_never_reopened(tenant: Tenant) -> None:
    """We reopen issues in Linear for our own bookkeeping. A customer who was
    told their question was answered should not watch it flip back."""
    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)
    request.status = SupportRequest.STATUS_DONE
    request.save(update_fields=["status"])

    with mock.patch.object(linear, "fetch_statuses") as fetch:
        support.sync_statuses([request])

    fetch.assert_not_called()


def test_an_unreachable_linear_leaves_the_last_status(tenant: Tenant) -> None:
    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)

    with mock.patch.object(linear, "fetch_statuses", return_value={}):
        support.sync_statuses([request])

    request.refresh_from_db()
    assert request.status == SupportRequest.STATUS_OPEN


def test_requests_without_an_issue_are_not_asked_about(tenant: Tenant) -> None:
    with mock.patch.object(linear, "create_support_issue", return_value=None):
        request = _create(tenant)

    with mock.patch.object(linear, "fetch_statuses") as fetch:
        support.sync_statuses([request])

    fetch.assert_not_called()


# --- status change notifications ------------------------------------------


def _synced_request(tenant: Tenant, new_status: str) -> "SupportRequest":
    """A request whose Linear status just moved to `new_status`, with the
    creation-time emails cleared away so tests only see the notification."""
    from django.core import mail

    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)
    mail.outbox.clear()
    with mock.patch.object(linear, "fetch_statuses", return_value={"iss_1": new_status}):
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
    assert "In progress" in notice.subject


def test_resolving_emails_the_resolved_wording(tenant: Tenant) -> None:
    from django.core import mail

    _synced_request(tenant, "done")

    assert len(mail.outbox) == 1
    assert "Resolved" in mail.outbox[0].subject
    assert "resolved" in mail.outbox[0].body


def test_an_unchanged_status_sends_nothing(tenant: Tenant) -> None:
    from django.core import mail

    _synced_request(tenant, "open")

    assert mail.outbox == []


def test_a_failing_notification_does_not_undo_the_status(tenant: Tenant) -> None:
    """The persist happens first on purpose; a mail hiccup must not leave the
    dashboard contradicting what Linear says."""
    from django.core import mail

    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)
    mail.outbox.clear()

    with (
        mock.patch.object(linear, "fetch_statuses", return_value={"iss_1": "in_progress"}),
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

    with mock.patch.object(linear, "create_support_issue", return_value=("iss_1", "PG-231")):
        request = _create(tenant)

    data = SupportRequestSerializer(request).data
    assert "linear_issue_id" not in data
    assert "message" not in data
    assert data["reference"] == "PG-231"
    assert data["status"] == "open"


# --- the client ------------------------------------------------------------


def test_graphql_errors_are_not_mistaken_for_success() -> None:
    """Linear answers 200 with an errors array, so the status code alone is
    not evidence that anything was created."""
    body = {"data": {"issueCreate": {"success": True}}, "errors": [{"message": "nope"}]}
    with mock.patch.object(linear, "_call", wraps=linear._call), \
         mock.patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = (
            __import__("json").dumps(body).encode()
        )
        with mock.patch.object(linear, "is_configured", return_value=True):
            assert linear.create_support_issue(title="t", description="d") is None


def test_unknown_state_types_are_dropped_rather_than_guessed() -> None:
    body = {"data": {"issues": {"nodes": [{"id": "iss_1", "state": {"type": "invented"}}]}}}
    with mock.patch.object(linear, "_call", return_value=body["data"]):
        assert linear.fetch_statuses(["iss_1"]) == {}


def test_optional_routing_is_only_sent_when_configured(settings) -> None:
    """Label and project are optional. Sending an empty string would be worse
    than omitting the field: Linear rejects the whole mutation for it."""
    settings.LINEAR_API_KEY = "key"
    settings.LINEAR_SUPPORT_TEAM_ID = "team"
    settings.LINEAR_SUPPORT_LABEL_ID = ""
    settings.LINEAR_SUPPORT_PROJECT_ID = ""

    captured = {}
    with mock.patch.object(linear, "_call", side_effect=lambda q, v: captured.update(v) or None):
        linear.create_support_issue(title="t", description="d")

    assert "labelIds" not in captured["input"]
    assert "projectId" not in captured["input"]


def test_project_and_label_reach_linear_when_set(settings) -> None:
    settings.LINEAR_API_KEY = "key"
    settings.LINEAR_SUPPORT_TEAM_ID = "team"
    settings.LINEAR_SUPPORT_LABEL_ID = "label-1"
    settings.LINEAR_SUPPORT_PROJECT_ID = "project-1"

    captured = {}
    with mock.patch.object(linear, "_call", side_effect=lambda q, v: captured.update(v) or None):
        linear.create_support_issue(title="t", description="d")

    assert captured["input"]["labelIds"] == ["label-1"]
    assert captured["input"]["projectId"] == "project-1"


def test_a_pasted_key_with_whitespace_still_authenticates(settings) -> None:
    """A trailing newline from a copy-paste is invisible in the Railway UI and
    reads as a bad credential. Stripping it is cheaper than debugging it."""
    settings.LINEAR_API_KEY = "lin_api_abc\n"
    settings.LINEAR_SUPPORT_TEAM_ID = "team"

    seen = []
    with mock.patch.object(linear, "_post", side_effect=lambda p, a: (seen.append(a), ({"data": {}}, None))[1]):
        linear.fetch_statuses(["iss_1"])

    assert seen[0] == "lin_api_abc"


def test_a_rejected_key_is_retried_with_bearer(settings) -> None:
    """Personal keys go in raw, OAuth tokens need Bearer. Trying the other one
    once on a 401 beats asking which kind somebody configured."""
    settings.LINEAR_API_KEY = "tok"
    settings.LINEAR_SUPPORT_TEAM_ID = "team"

    attempts = []

    def _post(payload, auth):
        attempts.append(auth)
        if not auth.startswith("Bearer"):
            return None, "HTTP 401: {}"
        return {"data": {"issues": {"nodes": []}}}, None

    with mock.patch.object(linear, "_post", _post):
        assert linear.fetch_statuses(["iss_1"]) == {}

    assert attempts == ["tok", "Bearer tok"]


def test_other_failures_are_not_retried(settings) -> None:
    """A timeout or a 500 is not an auth problem, and hammering it twice only
    doubles the time the customer waits for their confirmation."""
    settings.LINEAR_API_KEY = "tok"
    settings.LINEAR_SUPPORT_TEAM_ID = "team"

    attempts = []

    def _post(payload, auth):
        attempts.append(auth)
        return None, "HTTP 500: server error"

    with mock.patch.object(linear, "_post", _post):
        assert linear.fetch_statuses(["iss_1"]) == {}

    assert attempts == ["tok"]

# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""The helpdesk client's own logic: which ticket type a topic files under, and
how a ticket's stage reads back as one of our statuses (PG-360)."""
from unittest import mock

import pytest
from django.test import override_settings

from payglue_backend.tenants import helpdesk

TYPES = [
    {"id": "ticket_type_billing", "slug": "billing-or-plan", "category": "customer"},
    {"id": "ticket_type_else", "slug": "something-else", "category": "customer"},
    {"id": "ticket_type_internal", "slug": "billing-or-plan-internal", "category": "back_office"},
]


@pytest.fixture(autouse=True)
def configured():
    with override_settings(FEEDBACKOS_URL="https://hub.example.com/", FEEDBACKOS_API_KEY="k"):
        helpdesk._reset_cache()
        yield
        helpdesk._reset_cache()


def test_a_topic_files_under_its_customer_type_and_unknown_ones_under_else() -> None:
    with mock.patch.object(helpdesk, "_call", return_value=TYPES):
        assert helpdesk._ticket_type_id("billing") == "ticket_type_billing"
        assert helpdesk._ticket_type_id("nonsense") == "ticket_type_else"


def test_a_ticket_is_opened_with_requester_type_and_internal_note() -> None:
    calls = []

    def fake(path, *, method="GET", payload=None):
        calls.append((method, path, payload))
        if path == "users/identify":
            return {"principalId": "principal_1"}
        if path == "ticket-types":
            return TYPES
        if path == "tickets":
            return {"id": "ticket_9", "number": 9, "reference": "#9"}
        return {}

    with mock.patch.object(helpdesk, "_call", side_effect=fake):
        result = helpdesk.create_support_ticket(
            title="Wrong VAT",
            message="Please fix",
            topic="billing",
            email="a@example.com",
            name="Ada",
            internal_note="Service PIN: none\n",
        )

    assert result == ("ticket_9", "#9")
    ticket = next(p for m, path, p in calls if path == "tickets")
    assert ticket == {
        "title": "Wrong VAT",
        "description": "Please fix",
        "requesterPrincipalId": "principal_1",
        "descriptionFromRequester": True,
        "ticketTypeId": "ticket_type_billing",
    }
    assert ("POST", "tickets/ticket_9/note", {"content": "- Service PIN: none"}) in calls


def _open_ticket(fake) -> None:
    with mock.patch.object(helpdesk, "_call", side_effect=fake):
        helpdesk.create_support_ticket(
            title="Wrong VAT",
            message="Please fix",
            topic="billing",
            email="a@example.com",
            name="Ada",
            internal_note="",
        )


def test_a_new_ticket_goes_to_the_default_assignee() -> None:
    calls = []

    def fake(path, *, method="GET", payload=None):
        calls.append((method, path, payload))
        if path == "users/identify":
            return {"principalId": "principal_1"}
        if path == "ticket-types":
            return TYPES
        return {"id": "ticket_9", "number": 9}

    with override_settings(FEEDBACKOS_DEFAULT_ASSIGNEE="principal_agent"):
        _open_ticket(fake)

    assert (
        "POST",
        "tickets/ticket_9/assign",
        {"assigneePrincipalId": "principal_agent"},
    ) in calls


def test_a_new_ticket_stays_unassigned_without_a_default() -> None:
    calls = []

    def fake(path, *, method="GET", payload=None):
        calls.append(path)
        if path == "users/identify":
            return {"principalId": "principal_1"}
        if path == "ticket-types":
            return TYPES
        return {"id": "ticket_9", "number": 9}

    with override_settings(FEEDBACKOS_DEFAULT_ASSIGNEE=""):
        _open_ticket(fake)

    assert "tickets/ticket_9/assign" not in calls


def test_a_new_ticket_starts_with_the_default_priority() -> None:
    calls = []

    def fake(path, *, method="GET", payload=None):
        calls.append((path, payload))
        if path == "users/identify":
            return {"principalId": "principal_1"}
        if path == "ticket-types":
            return TYPES
        return {"id": "ticket_9", "number": 9}

    with override_settings(FEEDBACKOS_DEFAULT_PRIORITY="medium"):
        _open_ticket(fake)

    ticket = next(p for path, p in calls if path == "tickets")
    assert ticket["priority"] == "medium"


def test_no_requester_means_no_ticket() -> None:
    with mock.patch.object(helpdesk, "_call", return_value=None):
        assert (
            helpdesk.create_support_ticket(
                title="t", message="m", topic="bug", email="a@example.com", name="", internal_note=""
            )
            is None
        )


def test_stages_read_back_as_our_statuses() -> None:
    answers = {
        "tickets/ticket_1": {"stage": "received"},
        "tickets/ticket_2": {"stage": "awaiting_requester"},
        "tickets/ticket_3": {"stage": "resolved"},
        "tickets/ticket_4": {"stage": None, "status": {"category": "closed"}},
    }
    with mock.patch.object(helpdesk, "_call", side_effect=lambda path, **_: answers.get(path)):
        statuses = helpdesk.fetch_statuses(
            ["ticket_1", "ticket_2", "ticket_3", "ticket_4", "ticket_5", "plane-uuid"]
        )
    assert statuses == {
        "ticket_1": "open",
        "ticket_2": "in_progress",
        "ticket_3": "done",
        "ticket_4": "done",
    }


def test_off_without_url_or_key() -> None:
    with override_settings(FEEDBACKOS_API_KEY=""):
        assert helpdesk.is_configured() is False


def test_the_internal_note_is_one_fact_per_line() -> None:
    assert helpdesk._as_markdown_list("Publication: dodo\n\nService PIN: none\n") == (
        "- Publication: dodo\n- Service PIN: none"
    )


def test_the_whole_changelog_is_read_page_by_page() -> None:
    pages = {
        "changelog?published=true&limit=100": {
            "data": [{"id": "a"}],
            "meta": {"pagination": {"cursor": "c1", "hasMore": True}},
        },
        "changelog?published=true&limit=100&cursor=c1": {
            "data": [{"id": "b"}],
            "meta": {"pagination": {"cursor": None, "hasMore": False}},
        },
    }
    with mock.patch.object(helpdesk, "_call", side_effect=lambda path, **_: pages.get(path)):
        assert [row["id"] for row in helpdesk.all_published_changelog()] == ["a", "b"]


def test_a_failed_changelog_page_means_none_rather_than_a_partial_list() -> None:
    first = {"data": [{"id": "a"}], "meta": {"pagination": {"cursor": "c1", "hasMore": True}}}
    with mock.patch.object(
        helpdesk, "_call", side_effect=lambda path, **_: first if "cursor" not in path else None
    ):
        assert helpdesk.all_published_changelog() is None

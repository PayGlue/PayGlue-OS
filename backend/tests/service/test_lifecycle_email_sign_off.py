# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-182 follow-up: every customer-facing email closes the same way. The
seeded templates and the built-in fallback copy have to agree, otherwise a
customer's sign-off depends on whether a DB row happens to exist."""
import pytest

from payglue_backend.authn import lifecycle_emails as le
from payglue_backend.tenants.models import LifecycleEmailTemplate

pytestmark = pytest.mark.django_db

_SIGN_OFF = "__\nCheers,\nPayGlue - Team"

# The onboarding pair used to be the one exception, closing with a personal
# name. That name shipped in the public repository, so every self-hosted
# install signed its customers' welcome mail as somebody they have never heard
# of (PG-239). There is no exception any more, which is why this file no longer
# needs a second rule to keep the exception honest.


def test_every_seeded_template_uses_the_shared_sign_off() -> None:
    bodies = dict(LifecycleEmailTemplate.objects.values_list("trigger", "body"))
    assert bodies, "migrations should have seeded the templates"

    wrong = [trigger for trigger, body in bodies.items() if not body.endswith(_SIGN_OFF)]
    assert wrong == [], f"templates not ending with the shared sign-off: {wrong}"


def test_no_seeded_template_names_a_person_or_an_address() -> None:
    """The sign-off is not the only place a name can hide. This catches the body
    copy too, which is where "my name is ..., I'm the founder" sat."""
    rows = LifecycleEmailTemplate.objects.values_list("trigger", "subject", "body")
    offenders = [
        trigger
        for trigger, subject, body in rows
        if "payglue.io" in (subject + body).lower()
    ]
    assert offenders == [], f"templates naming a specific installation: {offenders}"


def test_fallback_copy_uses_the_same_sign_off() -> None:
    # These only render when a template row is missing entirely, which is
    # exactly when nobody would notice the drift.
    for name in [
        "_OWNER_TRANSFER_FALLBACK_BODY",
        "_OWNER_PROPOSED_FALLBACK_BODY",
        "_OWNER_CONFIRMED_FALLBACK_BODY",
        "_OWNER_REJECTED_FALLBACK_BODY",
        "_GHOST_ALERT_FALLBACK_BODY",
    ]:
        assert getattr(le, name).endswith(_SIGN_OFF), f"{name} has a different sign-off"


def test_all_four_transfer_triggers_have_a_template() -> None:
    """A missing row still sends (fallback copy), but it would be invisible in
    the admin, so that email's wording could never be edited."""
    seeded = set(LifecycleEmailTemplate.objects.values_list("trigger", flat=True))
    assert {
        LifecycleEmailTemplate.Trigger.OWNER_TRANSFER_REQUESTED,
        LifecycleEmailTemplate.Trigger.OWNER_TRANSFER_PROPOSED,
        LifecycleEmailTemplate.Trigger.OWNER_TRANSFER_CONFIRMED,
        LifecycleEmailTemplate.Trigger.OWNER_TRANSFER_REJECTED,
    } <= seeded

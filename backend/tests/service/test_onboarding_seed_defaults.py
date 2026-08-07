# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""What migration 0038 leaves behind on a fresh install.

Its own file because test_onboarding_emails.py switches both templates on for
every test in it. That fixture is right for testing the sending logic and
exactly wrong for testing the default, and one file cannot do both.
"""
import pytest

from payglue_backend.tenants.models import LifecycleEmailTemplate

pytestmark = pytest.mark.django_db

WELCOME = LifecycleEmailTemplate.Trigger.ONBOARDING_WELCOME
DAY15 = LifecycleEmailTemplate.Trigger.ONBOARDING_DAY15


def test_both_templates_are_seeded_but_switched_off() -> None:
    """They ship off, like every other customer-facing template.

    They used to ship on, carrying copy signed with one person's name and
    pointing at one particular installation. The console is not part of the
    open-source repository, so nobody self-hosting could have switched that off
    without going into the database (PG-239).
    """
    for trigger in (WELCOME, DAY15):
        template = LifecycleEmailTemplate.objects.filter(trigger=trigger).first()
        assert template is not None, f"{trigger} not seeded"
        assert not template.enabled, f"{trigger} would send unreviewed copy"


def test_the_seeded_copy_names_nobody() -> None:
    for trigger in (WELCOME, DAY15):
        template = LifecycleEmailTemplate.objects.get(trigger=trigger)
        text = (template.subject + template.body).lower()
        assert "payglue.io" not in text
        assert "founder" not in text

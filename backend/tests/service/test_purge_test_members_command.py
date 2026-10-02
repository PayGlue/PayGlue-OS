# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""PG-325: purge_test_members deletes test members only for publications that
set a retention, and only through the adapter's label filter."""
import pytest
from django.core.management import call_command

from payglue_backend.core.models import TenantContext
from payglue_backend.webhooks import wiring
from payglue_backend.webhooks.models import IntegrationConfig

pytestmark = pytest.mark.django_db


class _RecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def purge_test_members(self, tenant_ctx: TenantContext, older_than_days: int) -> dict[str, int]:
        self.calls.append((tenant_ctx.tenant_slug, older_than_days))
        return {"deleted": 3, "failed": 0}


def _ghost(slug: str, metadata: dict) -> None:
    IntegrationConfig.objects.create(
        tenant_slug=slug, provider_key="cms", enabled=True, provider_type="ghost", metadata=metadata
    )


def test_only_publications_with_a_retention_are_purged(monkeypatch) -> None:
    adapter = _RecordingAdapter()
    monkeypatch.setattr(wiring, "get_cms_adapter", lambda key: adapter)
    _ghost("demo", {"test_member_retention_days": 14})
    _ghost("keeps-everything", {})
    _ghost("explicit-zero", {"test_member_retention_days": 0})
    _ghost("garbage", {"test_member_retention_days": "soon"})

    call_command("purge_test_members")

    assert adapter.calls == [("demo", 14)]


def test_dry_run_touches_nothing(monkeypatch) -> None:
    adapter = _RecordingAdapter()
    monkeypatch.setattr(wiring, "get_cms_adapter", lambda key: adapter)
    _ghost("demo", {"test_member_retention_days": 7})

    call_command("purge_test_members", "--dry-run")

    assert adapter.calls == []


def test_one_failing_publication_does_not_stop_the_others(monkeypatch) -> None:
    class Flaky(_RecordingAdapter):
        def purge_test_members(self, tenant_ctx, older_than_days):
            if tenant_ctx.tenant_slug == "broken":
                raise RuntimeError("ghost down")
            return super().purge_test_members(tenant_ctx, older_than_days)

    adapter = Flaky()
    monkeypatch.setattr(wiring, "get_cms_adapter", lambda key: adapter)
    _ghost("broken", {"test_member_retention_days": 7})
    _ghost("fine", {"test_member_retention_days": 7})

    call_command("purge_test_members")

    assert ("fine", 7) in adapter.calls

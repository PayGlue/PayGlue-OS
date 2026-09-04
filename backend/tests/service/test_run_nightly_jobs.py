# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
"""run_nightly_jobs runs every job even when one of them fails, and reports
the failure through the exit code."""
import pytest
from django.core.management import call_command, get_commands

from payglue_backend.tenants.management.commands import run_nightly_jobs as module

pytestmark = pytest.mark.django_db


def _installed_jobs() -> list[str]:
    # The published tree ships without some jobs; the runner skips those.
    installed = get_commands()
    return [name for name, _ in module.JOBS if name in installed]


def test_runs_every_job_in_order(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    ran: list[str] = []
    monkeypatch.setattr(module, "call_command", lambda name, **kw: ran.append(name))

    call_command("run_nightly_jobs")

    assert ran == _installed_jobs()
    assert "nightly jobs done" in capsys.readouterr().out


def test_a_failing_job_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    ran: list[str] = []

    def fake(name, **kw):
        ran.append(name)
        if name == "expire_tester_access":
            raise RuntimeError("boom")

    monkeypatch.setattr(module, "call_command", fake)

    with pytest.raises(SystemExit) as exc:
        call_command("run_nightly_jobs")

    assert ran == _installed_jobs()
    assert "expire_tester_access" in str(exc.value)
    assert "boom" in capsys.readouterr().err


def test_dry_run_reaches_only_jobs_that_take_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, dict] = {}
    monkeypatch.setattr(module, "call_command", lambda name, **kw: seen.__setitem__(name, kw))

    call_command("run_nightly_jobs", "--dry-run")

    assert seen["send_lifecycle_emails"].get("dry_run") is True
    assert "dry_run" not in seen["purge_expired_logs"]


def test_a_job_that_is_not_installed_is_skipped_quietly(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """The published tree ships without the support status sync."""
    ran: list[str] = []
    monkeypatch.setattr(module, "call_command", lambda name, **kw: ran.append(name))
    installed = {name: "payglue_backend.tenants" for name, _ in module.JOBS if name != "sync_support_statuses"}
    monkeypatch.setattr(module, "get_commands", lambda: installed)

    call_command("run_nightly_jobs")

    assert "sync_support_statuses" not in ran
    assert len(ran) == len(module.JOBS) - 1
    out = capsys.readouterr().out
    assert "sync_support_statuses: not installed, skipped" in out
    assert "nightly jobs done" in out

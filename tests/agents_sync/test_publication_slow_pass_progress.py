"""Slow-pass progress lines for the agent publication job."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import (
    _publication_job_run as job_run,
    publication_job,
)
from tests._conftest_environment import redirect_sase_home
from tests.agents_sync._publication_job_helpers import publication_target


def _install_single_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = publication_target(tmp_path)
    monkeypatch.setattr(
        job_run,
        "list_project_records",
        lambda *_a, **_k: [
            SimpleNamespace(
                project_name="proj", workspace_dir="/tmp/proj", is_project=True
            )
        ],
    )
    monkeypatch.setattr(
        job_run,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(targets=(target,), outcomes=()),
    )
    monkeypatch.setattr(
        job_run,
        "drain_project",
        lambda *_a, **_k: SimpleNamespace(
            hood_drained=0,
            link_drained=0,
            referenced_by_drained=0,
            lock_busy=False,
            deferred=False,
            deferred_projects=0,
            retained_hints=False,
            claim_unfinished=False,
            error=None,
            outcome="empty",
        ),
    )
    monkeypatch.setattr(job_run, "safe_active_items", lambda _key: ())
    monkeypatch.setattr(job_run, "safe_referenced_by_count", lambda _key: 0)
    monkeypatch.setattr(job_run, "write_publication_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(job_run, "save_standing_alerts", lambda *_a, **_k: None)
    monkeypatch.setattr(job_run, "load_standing_alerts", lambda: {})


def test_fast_pass_emits_no_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _install_single_project(monkeypatch, tmp_path)

    messages: list[str] = []
    summary = publication_job.run_publication_job(
        work_budget_seconds=10, progress=messages.append
    )

    assert summary.projects == 1
    assert messages == []


def test_slow_pass_emits_progress_per_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _install_single_project(monkeypatch, tmp_path)

    calls = {"count": 0}
    base = 1000.0

    def fake_monotonic() -> float:
        calls["count"] += 1
        if calls["count"] == 1:
            return base
        return base + 61.0 + calls["count"] * 0.01

    monkeypatch.setattr(job_run.time, "monotonic", fake_monotonic)

    messages: list[str] = []
    summary = publication_job.run_publication_job(
        work_budget_seconds=240, progress=messages.append
    )

    assert summary.projects == 1
    assert any("project discovery" in message for message in messages)
    assert any("resolve_sync_targets" in message for message in messages)
    assert any("drain_project(proj)" in message for message in messages)
    assert any("heartbeat write" in message for message in messages)
    assert all("61." in message or "62." in message for message in messages)

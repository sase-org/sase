"""Missing-target handling for the publication job."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import (
    _publication_job_run as job_run,
    _publication_job_shared as job_shared,
    publication_job,
)
from sase.agents_sync.models import ProjectTarget, SyncOutcome
from tests._conftest_environment import redirect_sase_home
from tests.agents_sync._publication_job_helpers import publication_item


def _configure_missing_target_job(
    monkeypatch: pytest.MonkeyPatch,
    outcome: SyncOutcome,
) -> None:
    monkeypatch.setattr(
        job_run,
        "list_project_records",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                project_name="proj",
                workspace_dir="/tmp/proj",
                is_project=True,
            )
        ],
    )
    monkeypatch.setattr(
        job_run,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(targets=(), outcomes=(outcome,)),
    )


def _doorbell_path(tmp_path: Path, project_key: str = "proj") -> Path:
    return (
        tmp_path / ".sase" / "projects" / project_key / "agent_publication" / "doorbell"
    )


def test_skipped_target_with_no_rows_is_silent_and_never_rings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _configure_missing_target_job(
        monkeypatch,
        SyncOutcome(
            "proj",
            "Project",
            skip_reason="agents sidecar is disabled or unavailable",
        ),
    )
    monkeypatch.setattr(job_shared, "active_agent_publications", lambda _key: ())
    monkeypatch.setattr(
        job_shared,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        job_run,
        "ring_publication_doorbell",
        lambda key, _hint=None: pytest.fail("a skipped target must never ring"),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert summary.errors == 0
    assert summary.diagnostics == []
    assert not _doorbell_path(tmp_path).exists()
    assert summary.project_stats["proj"]["last_outcome"] == "target_skipped"
    assert summary.project_stats["proj"]["active_count"] == 0


def test_skipped_target_with_queued_row_counts_one_error_and_stays_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _configure_missing_target_job(
        monkeypatch,
        SyncOutcome(
            "proj",
            "Project",
            skip_reason="agents sidecar is disabled or unavailable",
        ),
    )
    item = publication_item("alice.athena.worker", "a" * 40, created_at=1)
    monkeypatch.setattr(job_shared, "active_agent_publications", lambda _key: (item,))
    monkeypatch.setattr(
        job_shared,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        job_run,
        "ring_publication_doorbell",
        lambda key, _hint=None: pytest.fail("a skipped target must never ring"),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert summary.errors == 1
    assert summary.diagnostics == [
        "proj: 1 queued publication request(s) cannot drain: "
        "agents sidecar is disabled or unavailable"
    ]
    assert summary.active_remaining == 1
    assert summary.parked == 0
    assert not _doorbell_path(tmp_path).exists()
    assert summary.project_stats["proj"]["last_outcome"] == "target_unavailable"
    assert summary.project_stats["proj"]["active_count"] == 1


def test_error_outcome_is_counted_once_without_a_second_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    _configure_missing_target_job(
        monkeypatch,
        SyncOutcome("proj", "Project", error="boom"),
    )
    monkeypatch.setattr(job_shared, "active_agent_publications", lambda _key: ())
    monkeypatch.setattr(
        job_shared,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        job_run,
        "ring_publication_doorbell",
        lambda key, _hint=None: pytest.fail("a missing target must never ring"),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert summary.errors == 1
    assert summary.diagnostics == ["proj: boom"]
    assert not _doorbell_path(tmp_path).exists()
    assert summary.project_stats["proj"]["last_outcome"] == "target_unavailable"


def test_sibling_project_with_valid_target_still_drains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target = ProjectTarget(
        project_key="proj2",
        project="Project 2",
        primary_checkout=tmp_path / "primary2",
        primary_roots=(tmp_path / "primary2",),
        sidecar_path=tmp_path / "agents2",
        remote_url="https://example.invalid/agents2.git",
    )
    monkeypatch.setattr(
        job_run,
        "list_project_records",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                project_name="proj",
                workspace_dir="/tmp/proj",
                is_project=True,
            ),
            SimpleNamespace(
                project_name="proj2",
                workspace_dir=str(tmp_path / "primary2"),
                is_project=True,
            ),
        ],
    )
    monkeypatch.setattr(
        job_run,
        "resolve_sync_targets",
        lambda _keys: SimpleNamespace(
            targets=(target,),
            outcomes=(
                SyncOutcome(
                    "proj",
                    "Project",
                    skip_reason="agents sidecar is disabled or unavailable",
                ),
            ),
        ),
    )
    monkeypatch.setattr(job_shared, "active_agent_publications", lambda _key: ())
    monkeypatch.setattr(
        job_shared,
        "list_referenced_by_requests",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        job_run,
        "ring_publication_doorbell",
        lambda key, _hint=None: pytest.fail("nothing here needs a ring"),
    )

    summary = publication_job.run_publication_job(work_budget_seconds=10)

    assert summary.errors == 0
    assert summary.diagnostics == []
    assert summary.project_stats["proj"]["last_outcome"] == "target_skipped"
    assert summary.project_stats["proj2"]["last_outcome"] == "idle"
    assert not _doorbell_path(tmp_path, "proj").exists()
    assert not _doorbell_path(tmp_path, "proj2").exists()

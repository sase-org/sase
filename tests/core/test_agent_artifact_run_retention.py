from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase._repo_inventory_models import RepoInventory, RepoRecord
from sase.bead.model import Status
import sase.core.agent_artifact_run_protection as protection
import sase.core.agent_artifact_run_retention as agent_artifact_run_retention
from sase.core.agent_artifact_run_retention import (
    AceRunProtectionSnapshot,
    AceRunRetentionPolicy,
    apply_ace_run_retention,
    plan_ace_run_retention,
)


def _run_dir(
    projects_root: Path,
    project: str,
    timestamp: str,
    *,
    done: bool = True,
    meta: dict[str, Any] | None = None,
) -> Path:
    path = (
        projects_root
        / project
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    path.mkdir(parents=True)
    if done:
        (path / "done.json").write_text(
            json.dumps(
                {"outcome": "completed", "name": meta.get("name") if meta else None}
            ),
            encoding="utf-8",
        )
    if meta is not None:
        (path / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return path


def _repo_record(name: str, path: Path, *, kind: str = "sidecar") -> RepoRecord:
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project="proj",
        project_key="proj",
        path=str(path),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        slug=f"proj--{name}" if kind == "sidecar" else None,
    )


def test_plan_protects_recent_referenced_open_bead_and_incomplete_runs(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _run_dir(projects_root, "proj", "20260501000000")
    recent = _run_dir(projects_root, "proj", "20260901000000")
    referenced = _run_dir(projects_root, "proj", "20260401000000")
    named = _run_dir(projects_root, "proj", "20260301000000", meta={"name": "keeper"})
    open_bead = _run_dir(
        projects_root,
        "proj",
        "20260201000000",
        meta={"bead_id": "sase-open"},
    )
    incomplete = _run_dir(projects_root, "proj", "20260101000000", done=False)
    future = _run_dir(projects_root, "proj", "20270401000000")
    snapshot = AceRunProtectionSnapshot(
        protected_dirs=frozenset({str(referenced.resolve())}),
        protected_agent_names=frozenset({"keeper"}),
        non_closed_bead_ids_by_project={"proj": frozenset({"sase-open"})},
    )

    plan = plan_ace_run_retention(
        AceRunRetentionPolicy(
            now=datetime(2026, 9, 12, 12, 0, 0),
            keep_recent_months=2,
            projects_root=projects_root,
        ),
        protections=snapshot,
    )

    assert [Path(item.artifact_dir) for item in plan.selected] == [old]
    reasons_by_path = {
        Path(item.artifact_dir): set(item.reasons) for item in plan.protected
    }
    assert "recent_month" in reasons_by_path[recent]
    assert "referenced_dir" in reasons_by_path[referenced]
    assert "referenced_agent" in reasons_by_path[named]
    assert "non_closed_bead" in reasons_by_path[open_bead]
    assert "not_terminal" in reasons_by_path[incomplete]
    assert "future_timestamp" in reasons_by_path[future]


def test_plan_reports_empty_out_of_range_shards(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    _run_dir(projects_root, "proj", "20260901000000")
    _run_dir(projects_root, "proj", "20260801000000")
    old_day = projects_root / "proj" / "artifacts" / "ace-run" / "202301" / "01"
    old_day.mkdir(parents=True)
    future_day = projects_root / "proj" / "artifacts" / "ace-run" / "202704" / "30"
    future_day.mkdir(parents=True)

    plan = plan_ace_run_retention(
        AceRunRetentionPolicy(
            now=datetime(2026, 9, 12, 12, 0, 0),
            keep_recent_months=2,
            projects_root=projects_root,
        ),
        protections=AceRunProtectionSnapshot(),
    )

    empty_paths = {Path(shard.path) for shard in plan.empty_out_of_range_shards}
    assert old_day in empty_paths
    assert old_day.parent in empty_paths
    assert future_day in empty_paths
    assert future_day.parent in empty_paths


def test_apply_removes_selected_runs_empty_shards_and_deindexes(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _run_dir(projects_root, "proj", "20260501000000")
    recent = _run_dir(projects_root, "proj", "20260901000000")
    future_day = projects_root / "proj" / "artifacts" / "ace-run" / "202704" / "30"
    future_day.mkdir(parents=True)
    deleted: list[Path] = []
    monkeypatch.setattr(
        "sase.core.agent_artifact_run_retention.delete_agent_artifact_index_artifacts",
        lambda paths, *, index_path=None: (
            deleted.extend(Path(path) for path in paths) or len(deleted)
        ),
    )
    plan = plan_ace_run_retention(
        AceRunRetentionPolicy(
            now=datetime(2026, 9, 12, 12, 0, 0),
            keep_recent_months=2,
            projects_root=projects_root,
        ),
        protections=AceRunProtectionSnapshot(),
    )

    result = apply_ace_run_retention(plan)

    assert result.removed_runs == 1
    assert result.removed_empty_shards == 2
    assert result.deindexed == 1
    assert deleted == [old]
    assert not old.exists()
    assert recent.exists()
    assert not future_day.exists()
    assert not future_day.parent.exists()


def test_protection_collector_uses_bead_projection_without_bead_text_walk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    beads = tmp_path / "beads"
    plans = tmp_path / "plans"
    for path in (projects_root, beads, plans):
        path.mkdir()
    referenced = (
        projects_root
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202604"
        / "01"
        / "20260401000000"
    )
    original_scan = protection._scan_text_root

    def fail_on_bead_walk(root: Path, **kwargs: Any) -> None:
        if root == beads:
            raise AssertionError("bead sidecar text walk should not run")
        original_scan(root, **kwargs)

    monkeypatch.setattr(protection, "_scan_text_root", fail_on_bead_walk)
    monkeypatch.setattr(
        protection.rust_beads,
        "list_issues",
        lambda _root: [
            SimpleNamespace(
                id="sase-open",
                status=Status.IN_PROGRESS,
                description=f"uses {referenced}",
                design="",
                refs=(),
                notes=(),
                links=(),
            )
        ],
    )

    snapshot = protection.collect_ace_run_retention_protections(
        projects_root=projects_root,
        artifact_index_path=tmp_path / "missing.sqlite",
        inventory=RepoInventory(
            (
                _repo_record("proj", tmp_path, kind="primary"),
                _repo_record("beads", beads),
                _repo_record("plans", plans),
            )
        ),
    )

    assert str(referenced.resolve(strict=False)) in snapshot.protected_dirs
    assert snapshot.protected_timestamps == frozenset({"20260401000000"})
    assert snapshot.non_closed_bead_ids_by_project == {"proj": frozenset({"sase-open"})}


def test_plan_degrades_to_continuation_unavailable_on_retention_value_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _run_dir(projects_root, "proj", "20260501000000")
    recent = _run_dir(projects_root, "proj", "20260901000000")

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("validation: runs has 11037 entries; maximum is 10000")

    monkeypatch.setattr(
        agent_artifact_run_retention,
        "plan_continuation_run_retention",
        _raise,
    )

    plan = plan_ace_run_retention(
        AceRunRetentionPolicy(
            now=datetime(2026, 9, 12, 12, 0, 0),
            keep_recent_months=2,
            projects_root=projects_root,
        ),
        protections=AceRunProtectionSnapshot(),
    )

    assert any(
        "continuation retention: validation: runs has 11037 entries" in source
        for source in plan.sources_unavailable
    )
    assert plan.counts.selected == 0
    reasons_by_path = {
        Path(item.artifact_dir): set(item.reasons) for item in plan.protected
    }
    assert "continuation_unavailable" in reasons_by_path[old]
    assert "continuation_unavailable" in reasons_by_path[recent]


def test_apply_still_raises_when_continuation_closure_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _run_dir(projects_root, "proj", "20260501000000")

    plan = plan_ace_run_retention(
        AceRunRetentionPolicy(
            now=datetime(2026, 9, 12, 12, 0, 0),
            keep_recent_months=2,
            projects_root=projects_root,
        ),
        protections=AceRunProtectionSnapshot(),
    )
    assert [Path(item.artifact_dir) for item in plan.selected] == [old]

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("validation: runs has 11037 entries; maximum is 10000")

    monkeypatch.setattr(
        "sase.core.continuation_retention.plan_continuation_run_retention",
        _raise,
    )

    with pytest.raises(ValueError, match="runs has 11037 entries"):
        apply_ace_run_retention(plan)

    assert old.exists()

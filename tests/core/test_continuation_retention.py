from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from sase._repo_inventory_models import RepoInventory
from sase.core.agent_artifact_run_retention import (
    AceRunProtectionSnapshot,
    AceRunRetentionPolicy,
    apply_ace_run_retention,
    plan_ace_run_retention,
)
from sase.core.continuation_retention import CONTINUATION_PORTABLE_LABEL_PREFIX
import sase.core.agent_artifact_run_protection as protection


def _run_dir(
    projects_root: Path,
    project: str,
    timestamp: str,
    *,
    done: bool = True,
    running: bool = False,
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
            json.dumps({"outcome": "completed"}), encoding="utf-8"
        )
    if running:
        (path / "running.json").write_text(json.dumps({"pid": 1}), encoding="utf-8")
    if meta is not None:
        (path / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return path


def _policy(projects_root: Path) -> AceRunRetentionPolicy:
    return AceRunRetentionPolicy(
        now=datetime(2026, 9, 12, 12, 0, 0),
        keep_recent_months=2,
        projects_root=projects_root,
    )


def test_plan_protects_live_continuation_ancestry_from_audit_probe(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _run_dir(
        projects_root,
        "proj",
        "20260501000000",
        meta={"continuation_node_id": "agent-delta:old"},
    )
    live = _run_dir(
        projects_root,
        "proj",
        "20260901000000",
        done=False,
        running=True,
        meta={
            "continuation_parent_node_ids": ["agent-delta:old"],
            "monitor_starter_artifacts_dir": str(old),
        },
    )
    unrelated = _run_dir(projects_root, "proj", "20260401000000")
    snapshot = protection.collect_ace_run_retention_protections(
        projects_root=projects_root,
        artifact_index_path=tmp_path / "missing.sqlite",
        inventory=RepoInventory(()),
    )

    plan = plan_ace_run_retention(_policy(projects_root), protections=snapshot)

    selected = {Path(item.artifact_dir) for item in plan.selected}
    reasons = {Path(item.artifact_dir): set(item.reasons) for item in plan.protected}
    assert unrelated in selected
    assert old not in selected
    assert live not in selected
    assert "continuation_ancestry" in reasons[old]
    assert "continuation_live" in reasons[live]
    assert plan.sources_unavailable == ()


def test_plan_reclaims_old_ancestry_after_safe_terminal_disposition(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _run_dir(
        projects_root,
        "proj",
        "20260501000000",
        meta={"continuation_node_id": "agent-delta:old"},
    )
    _run_dir(
        projects_root,
        "proj",
        "20260301000000",
        meta={
            "continuation_node_id": "monitor-result:done",
            "continuation_parent_node_ids": ["agent-delta:old"],
            "monitor_starter_artifacts_dir": str(old),
            "continuation_capture_disposition": "ok",
        },
    )

    plan = plan_ace_run_retention(
        _policy(projects_root),
        protections=AceRunProtectionSnapshot(),
    )

    selected = {Path(item.artifact_dir) for item in plan.selected}
    assert old in selected


def test_plan_protects_pending_delivery_ancestry(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    old = _run_dir(
        projects_root,
        "proj",
        "20260501000000",
        meta={"continuation_node_id": "agent-delta:old"},
    )
    pending = _run_dir(
        projects_root,
        "proj",
        "20260301000000",
        meta={
            "continuation_parent_node_ids": ["agent-delta:old"],
            "monitor_starter_artifacts_dir": str(old),
        },
    )
    delivery = pending / "continuation" / "delivery"
    delivery.mkdir(parents=True)
    (delivery / "branch.json").write_text(
        json.dumps({"disposition": "pending", "key": {"monitor_id": "m"}}),
        encoding="utf-8",
    )

    plan = plan_ace_run_retention(
        _policy(projects_root),
        protections=AceRunProtectionSnapshot(),
    )
    selected = {Path(item.artifact_dir) for item in plan.selected}
    reasons = {Path(item.artifact_dir): set(item.reasons) for item in plan.protected}
    assert old not in selected
    assert pending not in selected
    assert "continuation_recoverable" in reasons[pending]
    assert "continuation_ancestry" in reasons[old]


def test_apply_skips_dir_when_continuation_ancestry_appears(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _run_dir(projects_root, "proj", "20260501000000")
    plan = plan_ace_run_retention(
        _policy(projects_root),
        protections=AceRunProtectionSnapshot(),
    )
    assert [Path(item.artifact_dir) for item in plan.selected] == [old]

    _run_dir(
        projects_root,
        "proj",
        "20260902000000",
        done=False,
        running=True,
        meta={
            "continuation_parent_node_ids": ["agent-delta:old"],
            "monitor_starter_artifacts_dir": str(old),
            "continuation_node_id": "monitor-result:live",
        },
    )
    (old / "agent_meta.json").write_text(
        json.dumps({"continuation_node_id": "agent-delta:old"}),
        encoding="utf-8",
    )

    result = apply_ace_run_retention(plan)

    assert result.removed_runs == 0
    assert old.exists()
    assert any("continuation ancestry" in item for item in result.skipped)


def test_plan_protects_unreadable_continuation_metadata(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    broken = _run_dir(projects_root, "proj", "20260501000000")
    (broken / "agent_meta.json").write_text("{not-json", encoding="utf-8")

    plan = plan_ace_run_retention(
        _policy(projects_root),
        protections=AceRunProtectionSnapshot(),
    )
    selected = {Path(item.artifact_dir) for item in plan.selected}
    reasons = {Path(item.artifact_dir): set(item.reasons) for item in plan.protected}
    assert broken not in selected
    assert "continuation_recoverable" in reasons[broken]
    assert plan.sources_unavailable


def test_protection_collector_skips_continuation_portable_index_rows(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    from sase.core.artifact_file_types import ArtifactFile

    projects_root = tmp_path / "projects"
    old = _run_dir(projects_root, "proj", "20260401000000")
    row = ArtifactFile(
        id="explicit-continuation-1",
        label=f"{CONTINUATION_PORTABLE_LABEL_PREFIX}authored-checkpoint",
        kind="file",
        path=str(tmp_path / "portable.json"),
        explicit=True,
        agent_artifacts_dir=str(old),
    )
    monkeypatch.setattr(
        protection, "read_artifact_file_index", lambda _path=None: (row,)
    )

    dirs: set[str] = set()
    timestamps: set[str] = set()
    protection._collect_artifact_file_index_dirs(
        dirs=dirs,
        timestamps=timestamps,
        scanned=set(),
        unavailable=set(),
        index_path=tmp_path / "index.jsonl",
        projects_root=projects_root,
    )

    assert str(old.resolve()) not in dirs
    assert timestamps == set()

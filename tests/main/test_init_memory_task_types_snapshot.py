"""Committed task-type snapshot checks for ``sase memory init``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_handler,
    write,
)


def test_memory_check_names_task_type_digest_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    write(project_root / "sase.yml", "is_sase_managed: true\n")
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_handler() == 0
    assert plan_memory().actions == ()

    snapshot_path = project_root / "sase" / "task_types.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    flake = next(entry for entry in payload["types"] if entry["task_type"] == "flake")
    original = snapshot_path.read_text(encoding="utf-8")
    snapshot_path.write_text(
        original.replace(str(flake["digest"]), "0" * 64, 1),
        encoding="utf-8",
    )

    plan = plan_memory()
    snapshot_actions = [
        action for action in plan.actions if action.path == snapshot_path
    ]
    assert snapshot_actions
    assert any(
        "`flake` spec digest changed" in (action.detail or "")
        for action in snapshot_actions
    )
    assert any(
        "run `sase memory init`" in (action.detail or "") for action in snapshot_actions
    )


def test_memory_plan_generates_artifact_relation_note_and_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    write(project_root / "sase.yml", "is_sase_managed: true\n")
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_handler() == 0

    note_path = project_root / "sase" / "memory" / "artifact_relations.md"
    note = note_path.read_text(encoding="utf-8")
    assert "# Artifact Relation Registry" in note
    assert (
        "- `implements`: inverse `implemented-by`, directed yes, written by `cli`."
        in note
    )
    assert "`blocks`: use `sase bead dep` instead." in note
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Artifact Relation Registry" in agents
    assert "- `read`: inverse `read-by`, directed yes, written by `read`." in agents

    snapshot_path = project_root / "sase" / "artifact_relations.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert [entry["slug"] for entry in payload["relations"]] == [
        "cites",
        "read",
        "related",
        "supersedes",
        "implements",
        "derives-from",
    ]
    assert payload["reserved"] == [
        {"slug": "blocks", "pointer": "sase bead dep"},
        {"slug": "depends-on", "pointer": "sase bead dep"},
    ]


def test_memory_check_names_artifact_relation_snapshot_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    write(project_root / "sase.yml", "is_sase_managed: true\n")
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_handler() == 0
    snapshot_path = project_root / "sase" / "artifact_relations.json"
    original = snapshot_path.read_text(encoding="utf-8")
    snapshot_path.write_text(
        original.replace('"implements"', '"implemented"', 1),
        encoding="utf-8",
    )

    plan = plan_memory()
    snapshot_actions = [
        action for action in plan.actions if action.path == snapshot_path
    ]
    assert snapshot_actions
    assert any(
        "artifact relation registry snapshot changed" in (action.detail or "")
        for action in snapshot_actions
    )

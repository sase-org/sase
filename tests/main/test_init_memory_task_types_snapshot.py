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

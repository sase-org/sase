"""Tests scoping the generated task-type memory note to managed project repos."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_handler,
    short_note,
    write,
)

_GENERATED_TASK_TYPES_BODY = (
    "# Task Bead Types\n\n"
    "Stale generated catalog from an older SASE.\n\n"
    "## Types\n\n"
    "No agent-creatable task types are registered.\n"
)
_HAND_AUTHORED_TASK_TYPES_BODY = (
    "# Custom Task Catalog\n\nHand-authored home task types.\n"
)


def test_home_root_omits_task_types_memory_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert run_handler() == 0

    assert (project_root / "sase" / "memory" / "task_types.md").exists()
    assert (project_root / "sase" / "task_types.json").exists()
    assert not (home_root / "sase" / "memory" / "task_types.md").exists()
    assert not (home_root / "sase" / "task_types.json").exists()

    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    project_agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Task Bead Types" not in home_agents
    assert "Task Bead Types" in project_agents

    assert plan_memory().actions == ()


def test_retirement_deletes_generated_home_task_types_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(home_root / "sase.yml", 'memory:\n  h1_title: "Home Instructions"\n')

    assert run_handler() == 0

    task_types_path = home_root / "sase" / "memory" / "task_types.md"
    write(task_types_path, short_note(_GENERATED_TASK_TYPES_BODY))

    plan = plan_memory()
    changes = {(action.operation, action.path) for action in plan.actions}

    assert plan.blockers == ()
    assert ("delete", task_types_path) in changes
    assert not any("unreferenced memory file" in blocker for blocker in plan.blockers)

    assert run_handler() == 0

    assert not task_types_path.exists()
    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Task Bead Types" not in home_agents
    assert plan_memory().actions == ()


def test_retirement_leaves_hand_authored_home_task_types_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(home_root / "sase.yml", 'memory:\n  h1_title: "Home Instructions"\n')

    assert run_handler() == 0

    task_types_path = home_root / "sase" / "memory" / "task_types.md"
    write(task_types_path, short_note(_HAND_AUTHORED_TASK_TYPES_BODY))

    plan = plan_memory()
    assert plan.blockers == ()
    assert ("delete", task_types_path) not in {
        (action.operation, action.path) for action in plan.actions
    }

    assert run_handler() == 0

    assert task_types_path.exists()
    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Custom Task Catalog" in home_agents
    assert "Task Bead Types" not in home_agents

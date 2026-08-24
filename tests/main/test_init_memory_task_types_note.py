"""Tests scoping the generated task-type memory web to managed project repos."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.main.init_memory import root_rendering_task_types as task_types_rendering
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


def _fake_spec(slug: str, label: str) -> dict[str, Any]:
    return {
        "task_type": slug,
        "label": label,
        "summary": f"{label} summary.",
        "when_to_use": f"File one when {label.lower()} applies.",
        "agent_creatable": True,
        "fields": [],
    }


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
    assert (project_root / "sase" / "memory" / "task_types" / "bug.md").exists()
    assert (project_root / "sase" / "task_types.json").exists()
    assert not (home_root / "sase" / "memory" / "task_types.md").exists()
    assert not (home_root / "sase" / "memory" / "task_types").exists()
    assert not (home_root / "sase" / "task_types.json").exists()

    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    project_agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Task Bead Types" not in home_agents
    assert "Task Bead Types" in project_agents

    assert plan_memory().actions == ()


def test_project_root_writes_task_type_web_descriptor_and_strands(
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

    descriptor = project_root / "sase" / "memory" / "task_types.md"
    strand = project_root / "sase" / "memory" / "task_types" / "bug.md"
    descriptor_text = descriptor.read_text(encoding="utf-8")
    assert "web: true" in descriptor_text
    assert "roster: list" in descriptor_text
    assert "strand_noun: task type" in descriptor_text
    assert "- **Bug** (`bug`)" in descriptor_text

    strand_text = strand.read_text(encoding="utf-8")
    assert "keyword: Bug" in strand_text
    assert "Run `sase bead task-type show bug` for the full field list" in strand_text

    assert plan_memory().actions == ()


def test_retirement_deletes_stale_task_type_strand_file(
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

    real_specs = task_types_rendering._agent_creatable_task_type_specs
    monkeypatch.setattr(
        task_types_rendering,
        "_agent_creatable_task_type_specs",
        lambda: (*real_specs(), _fake_spec("zzz_temp", "Temp Type")),
    )

    assert run_handler() == 0

    stale_strand = project_root / "sase" / "memory" / "task_types" / "zzz_temp.md"
    assert stale_strand.exists()

    monkeypatch.setattr(
        task_types_rendering, "_agent_creatable_task_type_specs", real_specs
    )

    plan = plan_memory()
    changes = {(action.operation, action.path) for action in plan.actions}
    assert plan.blockers == ()
    assert ("delete", stale_strand) in changes

    assert run_handler() == 0
    assert not stale_strand.exists()
    assert plan_memory().actions == ()


def test_retirement_leaves_hand_authored_task_type_strand_file(
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

    rogue = project_root / "sase" / "memory" / "task_types" / "rogue.md"
    write(
        rogue,
        "---\nkeyword: Rogue\nsummary: Hand-authored.\n---\n\nNot generated.\n",
    )

    plan = plan_memory()
    assert plan.blockers == ()
    assert ("delete", rogue) not in {
        (action.operation, action.path) for action in plan.actions
    }

    assert run_handler() == 0
    assert rogue.exists()


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

"""Tests for memory reference validation and init registration."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main import init_memory_handler
from sase.main.init_memory.inventory import unreferenced_memory_files
from sase.main.init_memory_handler import plan_init_memory
from sase.main.init_registry import iter_init_command_specs
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_handler,
    run_memory,
    write,
)


def test_memory_reference_validation_uses_rendered_overlay(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    write(root / "AGENTS.md", "@sase/memory/generated.md\n")
    write(root / "sase" / "memory" / "detail.md", "# Detail\n")

    unreferenced = unreferenced_memory_files(
        root,
        overlay={
            root / "sase" / "memory" / "generated.md": "@sase/memory/detail.md\n",
        },
    )

    assert unreferenced == ()


def test_memory_plan_uses_amd_agents_overlay_when_project_is_opted_in(
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
    write(
        project_root / "sase.yml",
        'is_sase_managed: true\nmemory:\n  h1_title: "Managed Instructions"\n',
    )
    write(project_root / "AGENTS.md", "# Stale Instructions\n")
    write(
        project_root / "sase" / "memory" / "detail.md",
        "---\ntype: long\nparent: AGENTS.md\n---\n# Detail\n",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    assert ("overwrite", project_root / "AGENTS.md") in {
        (action.operation, action.path) for action in plan.actions
    }
    assert ("update", project_root / "sase" / "memory" / "detail.md") in {
        (action.operation, action.path) for action in plan.actions
    }


def test_memory_plan_repairs_unreferenced_long_memory_without_title(
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
    # Enabled project memory with no ``memory.h1_title`` derives a stable title.
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\nsdd:\n  version_controlled: true\n",
    )
    write(project_root / "AGENTS.md", "# Agent Instructions\n\n@sase/memory/sase.md\n")
    write(
        project_root / "sase" / "memory" / "sase.md",
        "---\ntype: short\nparent: AGENTS.md\n---\n# SASE\n",
    )
    write(
        project_root / "sase" / "memory" / "cli_rules.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: CLI rules reference.\n---\n"
        "# CLI Rules\n",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    assert ("overwrite", project_root / "AGENTS.md") in {
        (action.operation, action.path) for action in plan.actions
    }


def test_memory_apply_repairs_unreferenced_long_memory_without_title(
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
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\nsdd:\n  version_controlled: true\n",
    )
    write(project_root / "AGENTS.md", "# Agent Instructions\n\n@sase/memory/sase.md\n")
    write(
        project_root / "sase" / "memory" / "cli_rules.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: CLI rules reference.\n---\n"
        "# CLI Rules\n",
    )

    assert run_memory() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    first_line = agents.splitlines()[0]
    assert first_line.startswith("# ")
    assert first_line.endswith(" - Agent Instructions")
    assert "## 1. Tier 1 (short-term) Memory" in agents
    assert "## 2. Tier 2 (long-term) Memory" in agents
    assert "**`sase/memory/cli_rules.md`**" in agents
    # The repaired graph must validate cleanly on a follow-up run.
    assert run_memory() == 0
    assert plan_memory().actions == ()


def test_memory_plan_invalid_amd_title_still_blocks(
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
    write(
        project_root / "sase.yml",
        "is_sase_managed: true\nmemory:\n  h1_title: 123\n",
    )
    write(
        project_root / "sase" / "memory" / "cli_rules.md",
        "---\ntype: long\nparent: AGENTS.md\ndescription: CLI rules reference.\n---\n"
        "# CLI Rules\n",
    )

    plan = plan_memory()

    assert any(
        "memory.h1_title must be a string" in blocker for blocker in plan.blockers
    )


@pytest.mark.parametrize(
    ("notes", "expected"),
    [
        (
            {
                "child.md": (
                    "---\n"
                    "type: long\n"
                    "parent: memory/missing.md\n"
                    "description: Child.\n"
                    "---\n"
                    "# Child\n"
                )
            },
            (
                "invalid memory parent for sase/memory/child.md",
                "sase/memory/missing.md",
                "parent target does not exist",
            ),
        ),
        (
            {
                "parent.md": "---\ntype: short\nparent: AGENTS.md\n---\n# Parent\n",
                "child.md": (
                    "---\n"
                    "type: long\n"
                    "parent: sase/memory/parent.md\n"
                    "description: Child.\n"
                    "---\n"
                    "# Child\n"
                ),
            },
            (
                "invalid memory parent for sase/memory/child.md",
                "sase/memory/parent.md",
                "parent target is a short memory note",
            ),
        ),
        (
            {
                "self.md": (
                    "---\n"
                    "type: long\n"
                    "parent: sase/memory/self.md\n"
                    "description: Self.\n"
                    "---\n"
                    "# Self\n"
                )
            },
            (
                "invalid memory parent for sase/memory/self.md",
                "sase/memory/self.md",
                "parent points to the note itself",
            ),
        ),
        (
            {
                "a.md": (
                    "---\ntype: long\nparent: sase/memory/b.md\n"
                    "description: A.\n---\n# A\n"
                ),
                "b.md": (
                    "---\ntype: long\nparent: sase/memory/a.md\n"
                    "description: B.\n---\n# B\n"
                ),
            },
            (
                "memory parent cycle detected:",
                "sase/memory/a.md",
                "sase/memory/b.md",
            ),
        ),
        (
            {
                "a.md": (
                    "---\ntype: long\nparent: sase/memory/b.md\n"
                    "description: A.\n---\n# A\n"
                ),
                "b.md": (
                    "---\ntype: long\nparent: sase/memory/c.md\n"
                    "description: B.\n---\n# B\n"
                ),
                "c.md": (
                    "---\ntype: long\nparent: sase/memory/a.md\n"
                    "description: C.\n---\n# C\n"
                ),
            },
            (
                "memory parent cycle detected:",
                "sase/memory/a.md",
                "sase/memory/b.md",
                "sase/memory/c.md",
            ),
        ),
    ],
)
def test_memory_plan_blocks_invalid_memory_parents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    notes: dict[str, str],
    expected: tuple[str, ...],
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
    for name, content in notes.items():
        write(project_root / "sase" / "memory" / name, content)

    plan = plan_memory()
    blockers = "\n".join(plan.blockers)

    for item in expected:
        assert item in blockers
    assert "unreferenced memory file" not in blockers


def test_run_init_memory_returns_int_and_wrapper_raises_system_exit(
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

    assert run_memory() == 0
    assert run_handler() == 0


def test_init_memory_registry_runs_after_config() -> None:
    specs = {spec.name: spec for spec in iter_init_command_specs()}
    names = tuple(spec.name for spec in iter_init_command_specs())

    assert names == ("config", "memory", "repo", "skills")
    assert specs["memory"].plan is plan_init_memory
    assert specs["memory"].run is init_memory_handler.run_init_memory

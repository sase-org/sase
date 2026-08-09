"""Tests for generated glossary memory during ``sase memory init``."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd.constants import PROVIDER_SHIM_FILES
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_memory,
    write,
)


def _setup_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_config: str,
    home_config: str | None = None,
) -> tuple[Path, Path, Path]:
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
    write(project_root / "sase.yml", project_config)
    if home_config is not None:
        write(config_dir / "sase.yml", home_config)
    return project_root, home_root, config_dir


def test_memory_plan_generates_project_glossary_before_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Agent Clan:
      aliases:
        - agent clans
        - clan
      definition: >-
        A named, rootless container for agents that run in parallel.
    Workspace:
      definition: A numbered project checkout.
""",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    action_by_path = {action.path: action for action in plan.actions}
    glossary = action_by_path[project_root / "sase" / "memory" / "glossary.md"]
    glossary_text = str(glossary.new_content)
    assert "sase_generated: glossary" in glossary_text
    assert "# Glossary of Terms" in glossary_text
    assert "## Agent Clan" in glossary_text
    assert "ALIASES: clan" in glossary_text
    assert "agent clans" not in glossary_text
    assert "Aliases: clan" not in glossary_text

    agents = str(action_by_path[project_root / "AGENTS.md"].new_content)
    assert "### 1. Glossary of Terms (glossary)" in agents
    assert "#### 1.1 Agent Clan" in agents
    assert "A named, rootless container" in agents

    readme = str(
        action_by_path[project_root / "sase" / "memory" / "README.md"].new_content
    )
    assert "### `sase/memory/glossary.md`" in readme
    assert "Project-local glossary generated from sase.yml." in readme


def test_memory_plan_omits_alias_line_when_only_alias_is_term_plural(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Patch:
      aliases:
        - patches
      definition: A tracked unit of change.
""",
    )

    plan = plan_memory()

    assert plan.blockers == ()
    glossary = next(
        action for action in plan.actions if action.path.name == "glossary.md"
    )
    glossary_text = str(glossary.new_content)
    assert "## Patch\n\nA tracked unit of change." in glossary_text
    assert "## Patch\n\n\nA tracked unit of change." not in glossary_text
    assert "ALIASES:" not in glossary_text
    assert "Aliases:" not in glossary_text


def test_memory_apply_generates_glossary_idempotently_and_copies_provider_shims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Workspace:
      aliases:
        - workspaces
      definition: A numbered project checkout.
""",
    )

    assert run_memory() == 0

    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "### 1. Glossary of Terms (glossary)" in agents
    for filename in PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text(encoding="utf-8") == agents

    assert run_memory(check=True) == 0
    assert plan_memory().actions == ()


def test_memory_plan_blocks_invalid_project_glossary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Agent Clan:
      aliases:
        - workspace
      definition: A named container.
    Workspace:
      aliases:
        - workspace
      definition: A numbered checkout.
""",
    )

    plan = plan_memory()

    assert plan.actions == ()
    assert any(
        "glossary" in blocker.lower() and "workspace" in blocker.lower()
        for blocker in plan.blockers
    )


def test_memory_plan_refuses_to_overwrite_unmarked_glossary_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Workspace:
      definition: A numbered project checkout.
""",
    )
    write(
        project_root / "sase" / "memory" / "glossary.md",
        "---\ntype: short\nparent: AGENTS.md\n---\n\n# Glossary\n\nHuman note.\n",
    )

    plan = plan_memory()

    assert any(
        "refusing to overwrite unmarked glossary" in blocker
        for blocker in plan.blockers
    )
    assert project_root / "sase" / "memory" / "glossary.md" not in {
        action.path for action in plan.actions
    }


def test_memory_init_retires_generated_glossary_when_config_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="""
is_sase_managed: true
memory:
  glossary:
    Workspace:
      definition: A numbered project checkout.
""",
    )
    assert run_memory() == 0
    assert (project_root / "sase" / "memory" / "glossary.md").exists()

    write(project_root / "sase.yml", "is_sase_managed: true\n")

    plan = plan_memory()

    assert ("delete", project_root / "sase" / "memory" / "glossary.md") in {
        (action.operation, action.path) for action in plan.actions
    }

    assert run_memory() == 0
    assert not (project_root / "sase" / "memory" / "glossary.md").exists()
    assert "Glossary of Terms (glossary)" not in (project_root / "AGENTS.md").read_text(
        encoding="utf-8"
    )


def test_memory_init_ignores_home_glossary_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, home_root, _ = _setup_project(
        tmp_path,
        monkeypatch,
        project_config="is_sase_managed: true\n",
        home_config="""
memory:
  glossary:
    Home Term:
      definition: This must not become home memory.
""",
    )

    assert run_memory() == 0

    assert not (home_root / "sase" / "memory" / "glossary.md").exists()

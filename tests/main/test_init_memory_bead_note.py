"""Tests scoping the generated bead memory note to SASE-managed project repos."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.init_memory.root_rendering import render_generated_beads_memory_content
from tests.main.init_memory_handler_helpers import (
    long_note,
    patch_standard_paths,
    plan_memory,
    run_memory,
    write,
)


def test_home_root_omits_bead_memory_note(
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

    assert run_memory() == 0

    assert (project_root / "sase" / "memory" / "sase_beads.md").exists()
    assert not (home_root / "sase" / "memory" / "sase_beads.md").exists()

    project_agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "sase/memory/sase_beads.md" in project_agents
    assert "sase/memory/sase_beads.md" not in home_agents

    project_readme = (project_root / "sase" / "memory" / "README.md").read_text(
        encoding="utf-8"
    )
    home_readme = (home_root / "sase" / "memory" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "### `sase/memory/sase_beads.md`" in project_readme
    assert "### `sase/memory/sase_beads.md`" not in home_readme


def test_retirement_converges_in_one_pass(
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

    assert run_memory() == 0

    beads_content, error = render_generated_beads_memory_content()
    assert error is None
    assert beads_content is not None
    beads_path = home_root / "sase" / "memory" / "sase_beads.md"
    write(beads_path, beads_content)

    agents_path = home_root / "AGENTS.md"
    stale_agents = agents_path.read_text(encoding="utf-8").rstrip("\n")
    stale_agents += (
        "\n\n**`sase/memory/sase_beads.md`**  \nShared bead workflow guidance.\n"
    )
    agents_path.write_text(stale_agents, encoding="utf-8")

    plan = plan_memory()
    changes = {(action.operation, action.path) for action in plan.actions}

    assert plan.blockers == ()
    assert ("delete", beads_path) in changes

    assert run_memory() == 0

    assert not beads_path.exists()
    home_agents = agents_path.read_text(encoding="utf-8")
    home_readme = (home_root / "sase" / "memory" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "sase/memory/sase_beads.md" not in home_agents
    assert "### `sase/memory/sase_beads.md`" not in home_readme

    assert plan_memory().actions == ()


def test_retirement_guard_leaves_mismatched_home_copy_untouched(
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

    assert run_memory() == 0

    beads_path = home_root / "sase" / "memory" / "sase_beads.md"
    write(
        beads_path,
        long_note(
            "# Bead Notes\n\nHand-edited content.\n",
            description="Hand-edited bead notes.",
        ),
    )

    plan = plan_memory()

    assert plan.blockers == ()
    assert ("delete", beads_path) not in {
        (action.operation, action.path) for action in plan.actions
    }

    assert run_memory() == 0

    assert beads_path.exists()
    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "sase/memory/sase_beads.md" in home_agents


def test_retirement_reports_no_unreferenced_blocker(
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

    beads_content, error = render_generated_beads_memory_content()
    assert error is None
    assert beads_content is not None
    write(home_root / "sase" / "memory" / "sase_beads.md", beads_content)

    plan = plan_memory()
    assert plan.blockers == ()
    assert not any("unreferenced memory file" in blocker for blocker in plan.blockers)

    assert run_memory() == 0

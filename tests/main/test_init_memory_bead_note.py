"""Tests scoping generated project-long memory notes to managed project repos."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.main.init_memory.root_rendering import (
    render_generated_project_long_memory_contents,
)
from sase.memory.cli_read import handle_memory_read_command
from tests.main.init_memory_handler_helpers import (
    long_note,
    patch_standard_paths,
    plan_memory,
    run_memory,
    write,
)


def _generated_project_note(relative_path: str) -> str:
    contents, error = render_generated_project_long_memory_contents()
    assert error is None
    return contents[relative_path]


def test_home_root_omits_bead_memory_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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

    assert (project_root / "sase" / "memory" / "sase_artifacts.md").exists()
    assert (project_root / "sase" / "memory" / "sase_beads.md").exists()
    assert not (project_root / "sase" / "memory" / "sase_flags.md").exists()
    assert (project_root / "sase" / "memory" / "sase_sizes.md").exists()
    assert not (home_root / "sase" / "memory" / "sase_artifacts.md").exists()
    assert not (home_root / "sase" / "memory" / "sase_beads.md").exists()
    assert not (home_root / "sase" / "memory" / "sase_flags.md").exists()
    assert not (home_root / "sase" / "memory" / "sase_sizes.md").exists()

    project_agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    assert "sase/memory/sase_artifacts.md" in project_agents
    assert "sase/memory/sase_beads.md" in project_agents
    assert "sase/memory/sase_flags.md" not in project_agents
    assert "sase/memory/sase_sizes.md" not in project_agents
    assert "## Feature Flags" not in project_agents
    assert "sase/memory/sase_artifacts.md" not in home_agents
    assert "sase/memory/sase_beads.md" not in home_agents
    assert "sase/memory/sase_flags.md" not in home_agents
    assert "## Feature Flags" not in home_agents

    project_readme = (project_root / "sase" / "memory" / "README.md").read_text(
        encoding="utf-8"
    )
    home_readme = (home_root / "sase" / "memory" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "### `sase/memory/sase_artifacts.md`" in project_readme
    assert "### `sase/memory/sase_beads.md`" in project_readme
    assert "### `sase/memory/sase_flags.md`" not in project_readme
    assert "### `sase/memory/sase_sizes.md`" in project_readme
    assert "### `sase/memory/sase_artifacts.md`" not in home_readme
    assert "### `sase/memory/sase_beads.md`" not in home_readme
    assert "### `sase/memory/sase_flags.md`" not in home_readme
    assert "### `sase/memory/sase_sizes.md`" not in home_readme

    capsys.readouterr()
    monkeypatch.chdir(project_root)
    monkeypatch.setattr(Path, "home", lambda: home_root)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")
    handle_memory_read_command(
        argparse.Namespace(memory_path="sase_beads.md", reason="Need bead guidance")
    )
    read_output = capsys.readouterr().out
    assert "## Children" in read_output
    assert "**`sase/memory/sase_sizes.md`**" in read_output


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

    artifacts_content = _generated_project_note("sase/memory/sase_artifacts.md")
    artifacts_path = home_root / "sase" / "memory" / "sase_artifacts.md"
    write(artifacts_path, artifacts_content)
    beads_content = _generated_project_note("sase/memory/sase_beads.md")
    beads_path = home_root / "sase" / "memory" / "sase_beads.md"
    write(beads_path, beads_content)
    sizes_content = _generated_project_note("sase/memory/sase_sizes.md")
    sizes_path = home_root / "sase" / "memory" / "sase_sizes.md"
    write(sizes_path, sizes_content)

    agents_path = home_root / "AGENTS.md"
    stale_agents = agents_path.read_text(encoding="utf-8").rstrip("\n")
    stale_agents += (
        "\n\n**`sase/memory/sase_beads.md`**  \nShared bead workflow guidance.\n"
    )
    agents_path.write_text(stale_agents, encoding="utf-8")

    plan = plan_memory()
    changes = {(action.operation, action.path) for action in plan.actions}

    assert plan.blockers == ()
    assert ("delete", artifacts_path) in changes
    assert ("delete", beads_path) in changes
    assert ("delete", sizes_path) in changes

    assert run_memory() == 0

    assert not artifacts_path.exists()
    assert not beads_path.exists()
    assert not sizes_path.exists()
    home_agents = agents_path.read_text(encoding="utf-8")
    home_readme = (home_root / "sase" / "memory" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "sase/memory/sase_artifacts.md" not in home_agents
    assert "sase/memory/sase_beads.md" not in home_agents
    assert "sase/memory/sase_flags.md" not in home_agents
    assert "sase/memory/sase_sizes.md" not in home_agents
    assert "### `sase/memory/sase_artifacts.md`" not in home_readme
    assert "### `sase/memory/sase_beads.md`" not in home_readme
    assert "### `sase/memory/sase_flags.md`" not in home_readme
    assert "### `sase/memory/sase_sizes.md`" not in home_readme

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

    artifacts_content = _generated_project_note("sase/memory/sase_artifacts.md")
    write(home_root / "sase" / "memory" / "sase_artifacts.md", artifacts_content)
    beads_content = _generated_project_note("sase/memory/sase_beads.md")
    write(home_root / "sase" / "memory" / "sase_beads.md", beads_content)
    sizes_content = _generated_project_note("sase/memory/sase_sizes.md")
    write(home_root / "sase" / "memory" / "sase_sizes.md", sizes_content)

    plan = plan_memory()
    assert plan.blockers == ()
    assert not any("unreferenced memory file" in blocker for blocker in plan.blockers)

    assert run_memory() == 0

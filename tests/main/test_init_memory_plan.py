"""Tests for ``sase memory init`` planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd.constants import PROVIDER_SHIM_CONTENT, PROVIDER_SHIM_FILES
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_memory,
    write,
)


def test_memory_plan_missing_tree_reports_create_actions_without_writing(
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

    plan = plan_memory()

    assert {action.operation for action in plan.actions} == {"create"}
    action_by_path = {action.path: action for action in plan.actions}
    assert project_root / "sase" / "memory" / "sase.md" in action_by_path
    assert project_root / "sase" / "memory" / "task_types.md" in action_by_path
    assert home_root / "sase" / "memory" / "task_types.md" not in action_by_path
    assert project_root / "sase" / "memory" / "sase_artifacts.md" in action_by_path
    assert project_root / "sase" / "memory" / "sase_beads.md" in action_by_path
    assert project_root / "sase" / "memory" / "sase_flags.md" not in action_by_path
    assert project_root / "sase" / "memory" / "sase_sizes.md" in action_by_path
    assert project_root / "AGENTS.md" in {action.path for action in plan.actions}
    assert "### 2.1 `sase/memory/sase_artifacts.md`" in str(
        action_by_path[project_root / "AGENTS.md"].new_content
    )
    assert "### 2.2 `sase/memory/sase_beads.md`" in str(
        action_by_path[project_root / "AGENTS.md"].new_content
    )
    assert "`sase/memory/sase_flags.md`" not in str(
        action_by_path[project_root / "AGENTS.md"].new_content
    )
    assert "## Feature Flags" not in str(
        action_by_path[project_root / "sase" / "memory" / "sase.md"].new_content
    )
    assert "## Feature Flags" not in str(
        action_by_path[project_root / "AGENTS.md"].new_content
    )
    assert "sase/memory/sase_sizes.md" not in str(
        action_by_path[project_root / "AGENTS.md"].new_content
    )
    assert "### `sase/memory/sase_artifacts.md`" in str(
        action_by_path[project_root / "sase" / "memory" / "README.md"].new_content
    )
    assert "### `sase/memory/sase_beads.md`" in str(
        action_by_path[project_root / "sase" / "memory" / "README.md"].new_content
    )
    assert "### `sase/memory/sase_flags.md`" not in str(
        action_by_path[project_root / "sase" / "memory" / "README.md"].new_content
    )
    assert "### `sase/memory/sase_sizes.md`" in str(
        action_by_path[project_root / "sase" / "memory" / "README.md"].new_content
    )
    assert all(action.new_content is not None for action in plan.actions)
    assert not (project_root / "sase" / "memory").exists()
    assert not (home_root / "sase" / "memory").exists()


def test_memory_plan_non_project_reports_home_only_actions(
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
        project_is_vcs=False,
    )
    write(
        project_root / "sase.yml",
        """
linked_repos:
  - name: core
    path: ../sase-core
""",
    )

    plan = plan_memory()
    action_paths = {action.path for action in plan.actions}

    assert plan.blockers == ()
    assert home_root / "sase" / "memory" / "sase.md" in action_paths
    assert home_root / "sase" / "memory" / "task_types.md" not in action_paths
    assert home_root / "sase" / "memory" / "sase_artifacts.md" not in action_paths
    assert home_root / "sase" / "memory" / "sase_beads.md" not in action_paths
    assert home_root / "sase" / "memory" / "sase_flags.md" not in action_paths
    assert home_root / "sase" / "memory" / "sase_sizes.md" not in action_paths
    assert home_root / "AGENTS.md" in action_paths
    assert project_root / "sase" / "memory" / "sase.md" not in action_paths
    assert project_root / "sase" / "memory" / "sase_artifacts.md" not in action_paths
    assert project_root / "sase" / "memory" / "sase_beads.md" not in action_paths
    assert project_root / "sase" / "memory" / "sase_flags.md" not in action_paths
    assert project_root / "sase" / "memory" / "sase_sizes.md" not in action_paths
    assert project_root / "AGENTS.md" not in action_paths
    assert not (project_root / "sase" / "memory").exists()
    assert not (home_root / "sase" / "memory").exists()


def test_memory_check_missing_tree_reports_drift_without_writing(
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

    assert run_memory(check=True) == 1

    assert not (project_root / "sase" / "memory").exists()
    assert not (home_root / "sase" / "memory").exists()
    out = capsys.readouterr().out
    assert "SASE initialization check" in out
    assert "Needs attention:" in out
    assert "init memory" in out


def test_memory_plan_identical_generated_memory_is_empty(
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

    plan = plan_memory()

    assert plan.actions == ()
    assert plan.blockers == ()
    assert "current" in plan.summary


def test_memory_check_current_generated_memory_exits_zero(
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

    assert run_memory() == 0
    capsys.readouterr()

    assert run_memory(check=True) == 0

    out = capsys.readouterr().out
    assert "SASE is initialized. No init subcommands need to run." in out
    assert "Checked: memory." in out


def test_memory_plan_stale_provider_shim_reports_overwrite(
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
    (project_root / "CLAUDE.md").write_text("old instructions\n", encoding="utf-8")

    plan = plan_memory()

    assert {(action.operation, action.path) for action in plan.actions} == {
        ("overwrite", project_root / "CLAUDE.md")
    }


def test_memory_plan_stale_home_provider_shim_reports_overwrite(
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
    (home_root / "CLAUDE.md").write_text(PROVIDER_SHIM_CONTENT, encoding="utf-8")

    plan = plan_memory()

    assert {(action.operation, action.path) for action in plan.actions} == {
        ("overwrite", home_root / "CLAUDE.md")
    }


def test_memory_plan_creates_nested_agent_doc_provider_shims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    nested = project_root / "demos" / "tapes"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    assert run_memory() == 0
    write(nested / "AGENTS.md", "# Tape Instructions\n\nUse vhs for tapes.\n")

    plan = plan_memory()

    assert plan.blockers == ()
    assert {(action.operation, action.path) for action in plan.actions} == {
        ("create", nested / filename) for filename in PROVIDER_SHIM_FILES
    }


def test_memory_apply_creates_nested_agent_doc_provider_shims_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    nested = project_root / "demos" / "tapes"
    agents_content = "# Tape Instructions\n\nUse vhs for tapes.\n"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    assert run_memory() == 0
    write(nested / "AGENTS.md", agents_content)

    assert run_memory() == 0

    for filename in PROVIDER_SHIM_FILES:
        assert (nested / filename).read_text(encoding="utf-8") == agents_content
    assert plan_memory().actions == ()


def test_memory_plan_prunes_ignored_nested_agent_docs(
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
    write(project_root / ".sase" / "AGENTS.md", "# Ignored\n")
    write(project_root / "node_modules" / "pkg" / "AGENTS.md", "# Ignored\n")
    write(project_root / "sase" / "repos" / "linked" / "AGENTS.md", "# Ignored\n")

    plan = plan_memory()

    assert plan.actions == ()
    assert not (project_root / ".sase" / "CLAUDE.md").exists()
    assert not (project_root / "node_modules" / "pkg" / "CLAUDE.md").exists()
    assert not (project_root / "sase" / "repos" / "linked" / "CLAUDE.md").exists()


def test_memory_plan_preserves_existing_user_agents_file(
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
    (project_root / "sase.yml").unlink()
    write(
        project_root / "AGENTS.md",
        "# Custom Instructions\n\n@sase/memory/sase.md\n",
    )

    plan = plan_memory()

    assert project_root / "AGENTS.md" not in {action.path for action in plan.actions}
    assert (
        (project_root / "AGENTS.md")
        .read_text(encoding="utf-8")
        .startswith("# Custom Instructions")
    )


def test_memory_plan_invalid_linked_repo_config_returns_blocker_without_writing(
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
        """
is_sase_managed: true
linked_repos:
  - name: core
    path: ../sase-core
""",
    )

    plan = plan_memory()

    assert plan.actions == ()
    assert any("cannot generate project memory" in blocker for blocker in plan.blockers)
    assert not (project_root / "sase" / "memory").exists()


def test_memory_check_blockers_render_through_shared_output(
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
    write(
        project_root / "sase.yml",
        """
is_sase_managed: true
linked_repos:
  - name: core
    path: ../sase-core
""",
    )

    assert run_memory(check=True) == 1

    captured = capsys.readouterr()
    assert "Blockers:" in captured.out
    assert "cannot generate project memory" in captured.out
    assert captured.err == ""
    assert not (project_root / "sase" / "memory").exists()


def test_memory_init_migrates_legacy_tree_and_rewrites_parent_paths(
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
    legacy_note = project_root / "memory" / "detail.md"
    legacy_parent = project_root / "memory" / "parent.md"
    write(
        legacy_parent,
        "---\ntype: long\nparent: AGENTS.md\ndescription: Parent.\n---\n# Parent\n",
    )
    write(
        legacy_note,
        "---\n"
        "type: long\n"
        "parent: memory/parent.md\n"
        "description: Detail.\n"
        "---\n"
        "# Detail\n",
    )
    legacy_asset = project_root / "memory" / "assets" / "custom.txt"
    write(legacy_asset, "custom bytes\n")

    plan = plan_memory()
    changes = {(action.operation, action.path) for action in plan.actions}

    assert plan.blockers == ()
    assert ("create", project_root / "sase" / "memory" / "detail.md") in changes
    assert (
        "create",
        project_root / "sase" / "memory" / "assets" / "custom.txt",
    ) in changes
    assert ("delete", legacy_note) in changes
    assert ("delete", legacy_parent) in changes
    assert ("delete", legacy_asset) in changes

    assert run_memory() == 0

    assert not (project_root / "memory").exists()
    migrated_note = (project_root / "sase" / "memory" / "detail.md").read_text(
        encoding="utf-8"
    )
    assert "parent: sase/memory/parent.md" in migrated_note
    assert (project_root / "sase" / "memory" / "assets" / "custom.txt").read_text(
        encoding="utf-8"
    ) == "custom bytes\n"
    assert plan_memory().actions == ()


def test_memory_init_blocks_nonidentical_canonical_and_legacy_trees(
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
    write(project_root / "sase" / "memory" / "detail.md", "canonical\n")
    write(project_root / "memory" / "detail.md", "legacy\n")

    plan = plan_memory()

    assert any(
        "non-identical canonical and legacy trees" in item for item in plan.blockers
    )
    assert run_memory() == 1
    assert not (home_root / "sase" / "memory").exists()

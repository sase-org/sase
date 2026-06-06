"""Tests for ``sase memory init`` planning and memory validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd.constants import PROVIDER_SHIM_CONTENT
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
    assert project_root / "memory" / "short" / "sase.md" in {
        action.path for action in plan.actions
    }
    assert project_root / "AGENTS.md" in {action.path for action in plan.actions}
    assert not (project_root / "memory").exists()
    assert not (home_root / "memory").exists()


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

    assert not (project_root / "memory").exists()
    assert not (home_root / "memory").exists()
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
    write(
        project_root / "AGENTS.md",
        "# Custom Instructions\n\n@memory/short/sase.md\n",
    )

    plan = plan_memory()

    assert project_root / "AGENTS.md" not in {action.path for action in plan.actions}
    assert (
        (project_root / "AGENTS.md")
        .read_text(encoding="utf-8")
        .startswith("# Custom Instructions")
    )


def test_memory_plan_invalid_sibling_config_returns_blocker_without_writing(
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
sibling_repos:
  - name: core
    path: ../sase-core
""",
    )

    plan = plan_memory()

    assert plan.actions == ()
    assert any("cannot generate project memory" in blocker for blocker in plan.blockers)
    assert not (project_root / "memory").exists()


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
sibling_repos:
  - name: core
    path: ../sase-core
""",
    )

    assert run_memory(check=True) == 1

    captured = capsys.readouterr()
    assert "Blockers:" in captured.out
    assert "cannot generate project memory" in captured.out
    assert captured.err == ""
    assert not (project_root / "memory").exists()


def test_memory_reference_validation_uses_rendered_overlay(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    write(root / "AGENTS.md", "@memory/short/generated.md\n")
    write(root / "memory" / "long" / "detail.md", "# Detail\n")

    unreferenced = unreferenced_memory_files(
        root,
        overlay={
            root / "memory" / "short" / "generated.md": "@memory/long/detail.md\n",
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
    write(project_root / "sase.yml", 'amd_h1_title: "Managed Instructions"\n')
    write(project_root / "AGENTS.md", "# Stale Instructions\n")
    write(project_root / "memory" / "long" / "detail.md", "# Detail\n")

    plan = plan_memory()

    assert plan.blockers == ()
    assert ("overwrite", project_root / "AGENTS.md") in {
        (action.operation, action.path) for action in plan.actions
    }
    assert ("update", project_root / "memory" / "long" / "detail.md") in {
        (action.operation, action.path) for action in plan.actions
    }


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


def test_init_memory_registry_includes_memory_before_sdd() -> None:
    specs = {spec.name: spec for spec in iter_init_command_specs()}
    names = tuple(spec.name for spec in iter_init_command_specs())

    assert names[:3] == ("amd", "memory", "sdd")
    assert specs["memory"].plan is plan_init_memory
    assert specs["memory"].run is init_memory_handler.run_init_memory

"""Tests for project-root provider-shim retirement (E4)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

import sase.config.core as config_core
from sase.amd.constants import (
    HOME_PROVIDER_SHIM_FILES,
    PROJECT_PROVIDER_SHIM_FILES,
    PROVIDER_SHIM_CONTENT,
    RETIRED_PROJECT_PROVIDER_SHIM_FILES,
)
from sase.main import init_memory_handler
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_memory,
    write,
)


def _retired_paths(root: Path) -> list[Path]:
    return [root / filename for filename in RETIRED_PROJECT_PROVIDER_SHIM_FILES]


def test_project_root_retirement_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    for path in _retired_paths(project_root):
        write(path, agents)

    plan = plan_memory()
    assert plan.blockers == ()
    assert {(action.operation, action.path) for action in plan.actions} == {
        ("delete", path) for path in _retired_paths(project_root)
    }
    assert run_memory(check=True) == 1

    assert run_memory() == 0
    for path in _retired_paths(project_root):
        assert not path.exists()
    for filename in PROJECT_PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text(encoding="utf-8") == (
            project_root / "AGENTS.md"
        ).read_text(encoding="utf-8")

    second = plan_memory()
    assert second.blockers == ()
    assert second.actions == ()
    for path in _retired_paths(project_root):
        assert not path.exists()
    assert run_memory(check=True) == 0


def test_custom_retired_file_is_kept_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
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
    custom = "# Keep this Gemini file\n"
    write(project_root / "GEMINI.md", custom)
    write(project_root / "QWEN.md", PROVIDER_SHIM_CONTENT)

    plan = plan_memory()
    assert plan.blockers == ()
    assert any(
        "GEMINI.md" in warning and "custom retired" in warning
        for warning in plan.warnings
    )
    assert not any("GEMINI.md" in blocker for blocker in plan.blockers)
    qwen = project_root / "QWEN.md"
    assert any(
        action.operation == "delete" and action.path == qwen for action in plan.actions
    )
    assert not any(action.path == project_root / "GEMINI.md" for action in plan.actions)

    assert run_memory() == 0
    captured = capsys.readouterr()
    assert "custom retired" in captured.err or "custom retired" in captured.out
    assert (project_root / "GEMINI.md").read_text(encoding="utf-8") == custom
    assert not qwen.exists()


def test_home_root_keeps_four_provider_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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

    home_agents = (home_root / "AGENTS.md").read_text(encoding="utf-8")
    for filename in HOME_PROVIDER_SHIM_FILES:
        assert (home_root / filename).read_text(encoding="utf-8") == home_agents
    plan = plan_memory()
    home_deletes = tuple(
        action
        for action in plan.actions
        if action.operation == "delete"
        and action.path.is_relative_to(home_root)
        and action.path.name in RETIRED_PROJECT_PROVIDER_SHIM_FILES
    )
    assert home_deletes == ()


def test_chezmoi_root_still_writes_four_provider_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    project_root.mkdir()
    home_root.mkdir()
    chezmoi_home.mkdir(parents=True)
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=True,
    )
    monkeypatch.setattr(init_memory_handler, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(config_core, "CHEZMOI_HOME", chezmoi_home)

    def fake_deploy(paths: Iterable[Path], **_kwargs: object) -> int:
        del paths
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert run_memory() == 0

    agents = (chezmoi_home / "AGENTS.md").read_text(encoding="utf-8")
    for filename in HOME_PROVIDER_SHIM_FILES:
        assert (chezmoi_home / filename).read_text(encoding="utf-8") == agents
        assert not (chezmoi_home / f"{filename}.tmpl").exists()
    plan = plan_memory()
    chezmoi_deletes = tuple(
        action
        for action in plan.actions
        if action.operation == "delete"
        and action.path.is_relative_to(chezmoi_home)
        and action.path.name in RETIRED_PROJECT_PROVIDER_SHIM_FILES
    )
    assert chezmoi_deletes == ()


def test_nested_agents_retirement_deletes_identical_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    agents_content = "# Tape Instructions\n\nUse vhs for tapes.\n"
    write(nested / "AGENTS.md", agents_content)
    for filename in RETIRED_PROJECT_PROVIDER_SHIM_FILES:
        write(nested / filename, agents_content)

    plan = plan_memory()
    assert plan.blockers == ()
    assert {("create", nested / "CLAUDE.md")}.issubset(
        {(action.operation, action.path) for action in plan.actions}
    )
    assert {
        ("delete", nested / filename)
        for filename in RETIRED_PROJECT_PROVIDER_SHIM_FILES
    }.issubset({(action.operation, action.path) for action in plan.actions})

    assert run_memory() == 0
    assert (nested / "CLAUDE.md").read_text(encoding="utf-8") == agents_content
    for filename in RETIRED_PROJECT_PROVIDER_SHIM_FILES:
        assert not (nested / filename).exists()
    assert plan_memory().actions == ()

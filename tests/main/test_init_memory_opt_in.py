"""Tests for project memory opt-in behavior."""

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


@pytest.mark.parametrize(
    "local_config",
    [
        None,
        "is_sase_managed: false\nlinked_repos:\n  - malformed\n",
        "memory:\n  enabled: true\n",
        'amd_h1_title: "Legacy title is not an opt-in"\n',
    ],
)
def test_unmanaged_project_does_not_manage_memory_or_root_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    local_config: str | None,
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
    config_path = project_root / "sase.yml"
    if local_config is None:
        config_path.unlink()
    else:
        write(config_path, local_config)
    # A merged/global opt-in must not authorize project writes.
    write(config_dir / "sase.yml", "is_sase_managed: true\n")
    agents_content = "# Custom Project Instructions\n\nDo not replace this.\n"
    memory_content = "---\ntype: long\nparent: memory/missing.md\n---\n# Existing\n"
    write(project_root / "AGENTS.md", agents_content)
    write(project_root / "memory" / "existing.md", memory_content)

    plan = plan_memory()

    project_actions = tuple(
        action for action in plan.actions if action.path.is_relative_to(project_root)
    )
    assert plan.blockers == ()
    assert {action.path for action in project_actions} == {
        project_root / filename for filename in PROVIDER_SHIM_FILES
    }
    assert project_root / "AGENTS.md" not in {action.path for action in project_actions}

    assert run_memory() == 0
    assert (project_root / "AGENTS.md").read_text(encoding="utf-8") == agents_content
    assert (project_root / "memory" / "existing.md").read_text(
        encoding="utf-8"
    ) == memory_content
    assert not (project_root / "memory" / "sase.md").exists()
    for filename in PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text(encoding="utf-8") == agents_content


def test_enable_project_memory_creates_local_config_before_initializing(
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

    assert run_memory(enable_project_memory=True) == 0

    assert (project_root / "sase.yml").read_text(encoding="utf-8") == (
        "is_sase_managed: true\n"
    )
    assert (project_root / "memory" / "sase.md").is_file()
    assert (project_root / "AGENTS.md").is_file()


def test_enable_project_memory_preserves_existing_local_config(
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
        "# Keep this comment\nlinked_repos: []\nis_sase_managed: false # opt in\n",
    )

    assert run_memory(enable_project_memory=True) == 0

    config_text = (project_root / "sase.yml").read_text(encoding="utf-8")
    assert config_text == (
        "# Keep this comment\nlinked_repos: []\nis_sase_managed: true # opt in\n"
    )


def test_enable_project_memory_rejects_check_without_writing(
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
    (project_root / "sase.yml").unlink()

    assert run_memory(check=True, enable_project_memory=True) == 1

    assert not (project_root / "sase.yml").exists()
    assert "cannot be combined with --check" in capsys.readouterr().err


@pytest.mark.parametrize(
    "config_text, expected_error",
    [
        ("- not\n- a mapping\n", "expected a YAML mapping"),
        ("is_sase_managed: [\n", "failed to parse YAML"),
        ('is_sase_managed: "yes"\n', "is_sase_managed must be a boolean"),
        ("is_sase_managed: 1\n", "is_sase_managed must be a boolean"),
    ],
)
def test_invalid_project_memory_opt_in_blocks_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_text: str,
    expected_error: str,
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
    write(project_root / "sase.yml", config_text)

    plan = plan_memory()

    assert plan.actions == ()
    assert any(expected_error in blocker for blocker in plan.blockers)
    assert run_memory() == 1
    assert not (project_root / "memory").exists()
    assert not (project_root / "AGENTS.md").exists()
    assert not (home_root / "memory").exists()


def test_unmanaged_project_copies_root_and_nested_agents_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    nested = project_root / "demos" / "tapes"
    standalone = project_root / "docs"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(project_root / "sase.yml", "is_sase_managed: false\n")
    root_content = "# Root\n\nRoot bytes stay exact.\n"
    nested_content = "# Nested\n\nNested bytes stay exact.\n"
    standalone_content = "# Standalone Claude instructions\n"
    write(project_root / "AGENTS.md", root_content)
    write(nested / "AGENTS.md", nested_content)
    write(standalone / "CLAUDE.md", standalone_content)

    assert run_memory() == 0

    for filename in PROVIDER_SHIM_FILES:
        assert (project_root / filename).read_text(encoding="utf-8") == root_content
        assert (nested / filename).read_text(encoding="utf-8") == nested_content
    assert (standalone / "CLAUDE.md").read_text(encoding="utf-8") == (
        standalone_content
    )
    for filename in set(PROVIDER_SHIM_FILES) - {"CLAUDE.md"}:
        assert not (standalone / filename).exists()
    assert not (project_root / "memory").exists()
    assert plan_memory().actions == ()

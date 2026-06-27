"""Tests for the ``sase memory init`` command."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.amd.constants import PROVIDER_SHIM_FILES
from tests.main.init_memory_handler_helpers import (
    SASE_MEMORY_HEADER,
    patch_standard_paths,
    run_handler,
    single_line,
    write,
)


def test_init_memory_uses_local_linked_repos_for_project_and_global_for_home(
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

    # The project config uses the canonical ``linked_repos`` key while the
    # global config keeps the deprecated ``sibling_repos`` alias, proving both
    # the canonical key and the legacy fallback drive memory generation.
    write(
        project_root / "sase.yml",
        """
linked_repos:
  - name: core
    path: ../local-core
    description: Local Rust core.
""",
    )
    write(
        config_dir / "sase.yml",
        """
sibling_repos:
  - name: github
    path: /global/github
    description: Global GitHub plugin.
""",
    )

    assert run_handler() == 0
    out = capsys.readouterr().out
    assert "init memory: initialized memory" in out

    project_memory = (project_root / "memory" / "sase.md").read_text()
    home_memory = (home_root / "memory" / "sase.md").read_text()
    assert "`core`: Local Rust core." in project_memory
    assert "`github`: Global GitHub plugin." not in project_memory
    assert "../local-core" not in project_memory
    assert "`github`: Global GitHub plugin." in home_memory
    assert "`core`: Local Rust core." not in home_memory
    assert "/global/github" not in home_memory
    assert SASE_MEMORY_HEADER in project_memory
    assert SASE_MEMORY_HEADER in home_memory

    linked_trigger = (
        "When you need to make changes to files in a numbered-workspace linked "
        "repository or need to review numbered-workspace linked repository code, "
        "agents MUST run:"
    )
    for memory in (project_memory, home_memory):
        assert linked_trigger in single_line(memory)
        assert "linked reads/writes" in memory
        assert "When a linked repository needs changes, agents MUST run:" not in memory
        assert "linked edits" not in memory

    for root in (project_root, home_root):
        assert not (root / "memory" / "long").exists()
        assert (root / "memory" / "README.md").is_file()
        readme = (root / "memory" / "README.md").read_text()
        assert "`sase memory list`" in readme
        assert "`sase memory init`" in readme
        assert "Non-README Markdown files live directly under `memory/`" in readme
        assert "`type: long` notes are detailed reference material" in readme
        agents = (root / "AGENTS.md").read_text()
        assert "### SASE = Structured Agentic Software Engineering (sase)" in agents
        assert "@memory/sase.md" not in agents
        # Provider files are byte-for-byte copies of ``AGENTS.md``.
        for filename in PROVIDER_SHIM_FILES:
            assert (root / filename).read_text() == agents


def test_init_memory_static_linked_repos_use_paths_without_workspace_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    static_one = tmp_path / "static-one"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    monkeypatch.setenv("STATIC_ONE", str(static_one))
    write(
        project_root / "sase.yml",
        """
linked_repos:
  - name: dotfiles
    path: $STATIC_ONE
    description: User dotfiles source.
    workspace:
      strategy: none
  - name: notes
    path: ../static-two
    description: Static notes checkout.
    workspace:
      strategy: none
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "sase.md").read_text()
    project_memory_line = single_line(project_memory)
    assert "Static-path linked repositories (`workspace.strategy: none`)" not in (
        project_memory
    )
    assert (
        "- `dotfiles`: User dotfiles source. This repo is defined in the "
        "`$STATIC_ONE/` directory."
    ) in project_memory_line
    assert (
        "- `notes`: Static notes checkout. This repo is defined in the "
        "`../static-two/` directory."
    ) in project_memory_line
    assert (
        'sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>'
        not in project_memory
    )


def test_init_memory_mixed_linked_repos_render_static_location_and_workspace_open(
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
linked_repos:
  - name: core
    path: ../sase-core
    description: Numbered Rust core checkout.
  - name: dotfiles
    path: ../dotfiles
    description: Static dotfiles source.
    workspace:
      strategy: none
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "sase.md").read_text()
    project_memory_line = single_line(project_memory)
    assert "Static-path linked repositories (`workspace.strategy: none`)" not in (
        project_memory
    )
    assert (
        "- `dotfiles`: Static dotfiles source. This repo is defined in the "
        "`../dotfiles/` directory."
    ) in project_memory_line
    assert "numbered-workspace linked repository" in project_memory
    assert (
        'sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>'
        in project_memory
    )
    assert "numbered-workspace linked reads/writes" in project_memory_line


def test_init_memory_static_relative_paths_use_configured_display_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_root = tmp_path / "primary" / "project"
    project_root = tmp_path / "managed" / "project_10"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    numbered_relative_path = tmp_path / "managed" / "shared"
    primary_root.mkdir(parents=True)
    project_root.mkdir(parents=True)
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    write(
        project_root / ".sase" / "checkout.json",
        f"""
{{
  "project_key": "org/project",
  "project_name": "project",
  "workspace_num": 10,
  "primary_workspace_dir": "{primary_root}",
  "registry_path": "/work/registry.json",
  "schema_version": 1
}}
""",
    )
    write(
        project_root / "sase.yml",
        """
linked_repos:
  - name: shared
    path: ../shared
    description: Static shared checkout.
    workspace:
      strategy: none
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "sase.md").read_text()
    assert (
        "- `shared`: Static shared checkout. This repo is defined in the "
        "`../shared/` directory."
    ) in single_line(project_memory)
    assert str((tmp_path / "primary" / "shared").resolve(strict=False)) not in (
        project_memory
    )
    assert str(numbered_relative_path.resolve(strict=False)) not in project_memory
    assert (
        'sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>'
        not in project_memory
    )


def test_init_memory_project_memory_includes_workspace_section(
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

    project_memory = (project_root / "memory" / "sase.md").read_text()
    home_memory = (home_root / "memory" / "sase.md").read_text()
    assert SASE_MEMORY_HEADER in project_memory
    assert "## Ephemeral `project_<N>` Workspace Directories" in project_memory
    assert "full clones of the project repo" in project_memory
    assert "directories are named `project_<N>`" in project_memory
    assert (
        'sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>'
        not in project_memory
    )
    assert (
        'sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>'
        not in home_memory
    )
    assert "{{ project }}" not in project_memory
    assert "Ephemeral" not in home_memory
    assert SASE_MEMORY_HEADER in home_memory

    plan_warning = (
        "IMPORTANT: Do NOT mention your workspace directory (or any sibling "
        "workspace directory) in any plan files that you generate using your "
        "`/sase_plan` skill. The agent(s) that implement the plan might not run "
        "in the same workspace directory as you!"
    )
    assert plan_warning in single_line(project_memory)
    assert "/sase_plan" not in home_memory


def test_init_memory_project_memory_uses_managed_checkout_marker_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project_10"
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
        project_root / ".sase" / "checkout.json",
        """
{
  "project_key": "org/project",
  "project_name": "project",
  "workspace_num": 10,
  "primary_workspace_dir": "/work/project",
  "registry_path": "/work/registry.json",
  "schema_version": 1
}
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "sase.md").read_text()
    assert "## Ephemeral `project_<N>` Workspace Directories" in project_memory
    assert "full clones of the project repo" in project_memory
    assert "project_10_<N>" not in project_memory


def test_init_memory_reports_missing_linked_repo_descriptions(
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
linked_repos:
  - name: core
    path: ../sase-core
""",
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "cannot generate project memory" in err
    assert "field 'description'" in err
    assert not (project_root / "memory").exists()

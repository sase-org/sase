"""Tests for the ``sase memory init`` command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.amd.constants import PROVIDER_SHIM_FILES
from sase.main import init_memory_handler
from sase.main.init_memory.roots import read_memory_directory_map_bytes
from sase.memory.inventory import stats_for_text
from tests.main.init_memory_handler_helpers import (
    SASE_MEMORY_HEADER,
    long_note,
    patch_standard_paths,
    plan_memory,
    run_handler,
    single_line,
    short_note,
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
is_sase_managed: true
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

    project_memory = (project_root / "sase" / "memory" / "sase.md").read_text()
    home_memory = (home_root / "sase" / "memory" / "sase.md").read_text()
    assert "`core`: Local Rust core." in project_memory
    assert "`github`: Global GitHub plugin." not in project_memory
    assert "../local-core" not in project_memory
    assert "`github`: Global GitHub plugin." in home_memory
    assert "`core`: Local Rust core." not in home_memory
    assert "/global/github" not in home_memory
    assert SASE_MEMORY_HEADER in project_memory
    assert SASE_MEMORY_HEADER in home_memory

    repo_trigger = (
        "When you need to read or modify files in any repository other than your "
        "own workspace checkout, agents MUST use your `/sase_repo` skill first."
    )
    for memory in (project_memory, home_memory):
        memory_line = single_line(memory)
        assert "## Repositories" in memory
        assert repo_trigger in memory_line
        assert "another SASE project's repo" in memory_line
        assert "GitHub repo not linked to the current project" in memory_line
        assert "Open different-project and unlinked GitHub repos as external repos" in (
            memory_line
        )
        assert "Use the path it prints as the only path for reads and writes" in (
            memory_line
        )
        assert (
            "This rule applies regardless of transport. Fetching a repository's "
            "files or history over the web"
        ) in memory_line
        assert "raw.githubusercontent.com" in memory_line
        assert "GitHub-API/`gh` file-content reads" in memory_line
        assert (
            "Web tools remain appropriate only for content a checkout does not contain"
        ) in memory_line
        assert (
            "IMPORTANT REMINDER: Do NOT locate, clone, or web-fetch another "
            "repo's contents any other way than by using `/sase_repo`!"
        ) in memory_line
        assert 'sase repo open <linked_repo> -r "<reason>"' not in memory

    for root in (project_root, home_root):
        assert not (root / "sase" / "memory" / "long").exists()
        assert (root / "sase" / "memory" / "README.md").is_file()
        readme = (root / "sase" / "memory" / "README.md").read_text()
        assert "`sase memory list`" in readme
        assert "`sase memory init`" in readme
        assert "`memory_sase_template`" in readme
        assert "`memory_readme_template`" in readme
        assert "Non-README Markdown files live directly under `sase/memory/`" in readme
        assert "`type: long` notes are detailed reference material" in readme
        agents = (root / "AGENTS.md").read_text()
        assert "### 1. SASE = Structured Agentic Software Engineering (sase)" in agents
        assert "@sase/memory/sase.md" not in agents
        # Provider files are byte-for-byte copies of ``AGENTS.md``.
        for filename in PROVIDER_SHIM_FILES:
            assert (root / filename).read_text() == agents


def test_init_memory_excludes_auto_clone_and_does_not_inject_managed_research(
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
    path: ../core
    description: Always-present core.
    auto_clone: true
  - name: plugin
    path: ../plugin
    description: Lazy plugin.
""",
    )

    assert run_handler() == 0

    memory = (project_root / "sase" / "memory" / "sase.md").read_text(encoding="utf-8")
    assert "`core`: Always-present core." not in memory
    assert "`plugin`: Lazy plugin." in memory
    assert "project--research" not in memory


def test_init_memory_renders_project_and_home_sidecars_with_expected_slugs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "sase"
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
repos:
  sidecar:
    - name: research
      description: Durable SASE research reports and generated media.
    - name: reports
      repo: example-org/custom-reports
      description: Project reports.
""",
    )
    write(
        config_dir / "sase.yml",
        """
repos:
  sidecar:
    - name: notes
      description: Home notes.
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "sase" / "memory" / "sase.md").read_text()
    home_memory = (home_root / "sase" / "memory" / "sase.md").read_text()
    assert (
        "- `sase--research`: Durable SASE research reports and generated media."
        in project_memory
    )
    assert "- `custom-reports`: Project reports." in project_memory
    assert "`notes`: Home notes." not in project_memory
    assert "- `notes`: Home notes." in home_memory
    assert "sase--research" not in home_memory
    assert "custom-reports" not in home_memory


def test_init_memory_skips_auto_cloned_and_disabled_sidecars_before_validation(
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
repos:
  sidecar:
    - auto_clone: true
    - disabled: true
    - name: artifacts
      description: Lazy project artifacts.
""",
    )

    assert run_handler() == 0

    memory = (project_root / "sase" / "memory" / "sase.md").read_text(encoding="utf-8")
    assert "- `project--artifacts`: Lazy project artifacts." in memory


def test_init_memory_default_linked_repos_opt_out(
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
default_linked_repos: false
linked_repos: []
""",
    )

    assert run_handler() == 0

    memory = (project_root / "sase" / "memory" / "sase.md").read_text(encoding="utf-8")
    assert "project--research" not in memory


def test_init_memory_non_project_initializes_home_only_without_project_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "not-project"
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
is_sase_managed: true
linked_repos:
  - name: core
    path: ../sase-core
""",
    )
    git_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(init_memory_handler.subprocess, "run", git_run)

    assert run_handler(no_commit=False) == 0

    out = capsys.readouterr().out
    assert "project memory target" not in out
    assert "home memory target" in out
    assert not (project_root / "sase" / "memory").exists()
    assert not (project_root / "AGENTS.md").exists()
    assert (home_root / "sase" / "memory" / "sase.md").exists()
    assert (home_root / "AGENTS.md").exists()
    git_run.assert_not_called()


def test_init_memory_renders_data_driven_readme_and_asset(
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
    extra_note = short_note("# Extra\n\nAlways loaded.\n")
    reference_note = long_note(
        "# Reference\n\nDetailed reference.\n",
        description="Detailed reference note.",
    )
    write(project_root / "sase" / "memory" / "extra.md", extra_note)
    write(project_root / "sase" / "memory" / "reference.md", reference_note)

    assert run_handler() == 0

    readme = (project_root / "sase" / "memory" / "README.md").read_text(
        encoding="utf-8"
    )
    assert (
        "![How SASE memory files are used](assets/memory-directory-map.png)" in readme
    )
    assert "## How Memory Files Are Used" in readme
    assert "## Memory Notes" in readme
    assert "## Statistics" in readme
    assert "## Commands" in readme
    assert readme.index("### `sase/memory/extra.md`") < readme.index(
        "### `sase/memory/sase.md`"
    )
    assert readme.index("### `sase/memory/sase.md`") < readme.index(
        "### `sase/memory/reference.md`"
    )
    assert "- Type: `short`" in readme
    assert "- Type: `long`" in readme
    assert "- Description: Detailed reference note." in readme
    assert "- Parent: `AGENTS.md`" in readme
    extra_stats = stats_for_text(
        (project_root / "sase" / "memory" / "extra.md").read_text(encoding="utf-8")
    )
    reference_stats = stats_for_text(
        (project_root / "sase" / "memory" / "reference.md").read_text(encoding="utf-8")
    )
    assert f"- Lines: {extra_stats.line_count}" in readme
    assert f"- Approx. tokens: {extra_stats.approx_token_count}" in readme
    assert f"- Lines: {reference_stats.line_count}" in readme
    assert f"- Approx. tokens: {reference_stats.approx_token_count}" in readme
    assert "- Total notes: 3" in readme
    assert "- Short notes: 2" in readme
    assert "- Long notes: 1" in readme

    asset_path = (
        project_root / "sase" / "memory" / "assets" / "memory-directory-map.png"
    )
    expected_asset = read_memory_directory_map_bytes()
    assert asset_path.read_bytes() == expected_asset
    assert run_handler(check=True) == 0

    asset_path.write_bytes(b"stale asset")
    plan = plan_memory()
    assert any(
        action.path == asset_path
        and action.operation == "update"
        and action.detail == "memory directory map asset"
        for action in plan.actions
    )
    assert run_handler() == 0
    assert asset_path.read_bytes() == expected_asset
    assert run_handler(check=True) == 0


def test_init_memory_legacy_workspace_config_uses_repo_open(
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
is_sase_managed: true
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

    project_memory = (project_root / "sase" / "memory" / "sase.md").read_text()
    project_memory_line = single_line(project_memory)
    assert "Static-path linked repositories (`workspace.strategy: none`)" not in (
        project_memory
    )
    assert "- `dotfiles`: User dotfiles source." in project_memory_line
    assert "- `notes`: Static notes checkout." in project_memory_line
    assert "agents MUST use your `/sase_repo` skill first" in project_memory_line


def test_init_memory_mixed_linked_repos_render_repo_open(
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
    description: Numbered Rust core checkout.
  - name: dotfiles
    path: ../dotfiles
    description: Static dotfiles source.
    workspace:
      strategy: none
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "sase" / "memory" / "sase.md").read_text()
    project_memory_line = single_line(project_memory)
    assert "Static-path linked repositories (`workspace.strategy: none`)" not in (
        project_memory
    )
    assert "- `dotfiles`: Static dotfiles source." in project_memory_line
    assert "configured linked repos and sidecars" in project_memory
    assert "agents MUST use your `/sase_repo` skill first" in project_memory_line
    assert "Use the path it prints as the only path" in project_memory_line


def test_init_memory_legacy_relative_paths_use_repo_open(
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
is_sase_managed: true
linked_repos:
  - name: shared
    path: ../shared
    description: Static shared checkout.
    workspace:
      strategy: none
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "sase" / "memory" / "sase.md").read_text()
    assert "- `shared`: Static shared checkout." in single_line(project_memory)
    assert str((tmp_path / "primary" / "shared").resolve(strict=False)) not in (
        project_memory
    )
    assert str(numbered_relative_path.resolve(strict=False)) not in project_memory
    assert "agents MUST use your `/sase_repo` skill first" in single_line(
        project_memory
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

    project_memory = (project_root / "sase" / "memory" / "sase.md").read_text()
    home_memory = (home_root / "sase" / "memory" / "sase.md").read_text()
    assert SASE_MEMORY_HEADER in project_memory
    assert "## Ephemeral `project_<N>` Workspace Directories" in project_memory
    assert "full clones of the project repo" in project_memory
    assert "directories are named `project_<N>`" in project_memory
    assert "project--research" not in project_memory
    assert "agents MUST use your `/sase_repo` skill first" in single_line(
        project_memory
    )
    assert "agents MUST use your `/sase_repo` skill first" in single_line(home_memory)
    assert "No linked repositories are configured for this context." in home_memory
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

    project_memory = (project_root / "sase" / "memory" / "sase.md").read_text()
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
is_sase_managed: true
linked_repos:
  - name: core
    path: ../sase-core
""",
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "cannot generate project memory" in err
    assert "field 'description'" in err
    assert not (project_root / "sase" / "memory").exists()


def test_init_memory_reports_missing_sidecar_descriptions(
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
repos:
  sidecar:
    - name: research
""",
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "cannot generate project memory" in err
    assert "repos.sidecar[0] ('research')" in err
    assert "field 'description'" in err
    assert not (project_root / "sase" / "memory").exists()

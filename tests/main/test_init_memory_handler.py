"""Tests for the ``sase memory init`` command."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_handler,
    run_memory,
    write,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _prettier_command() -> list[str]:
    prettier = shutil.which("prettier")
    if prettier is not None:
        return [prettier]
    local_prettier = _REPO_ROOT / "node_modules" / ".bin" / "prettier"
    if local_prettier.exists():
        return [str(local_prettier)]
    pytest.skip("prettier not installed")


def _single_line(text: str) -> str:
    return " ".join(text.split())


def test_init_memory_uses_local_siblings_for_project_and_global_for_home(
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

    project_memory = (project_root / "memory" / "short" / "sase.md").read_text()
    home_memory = (home_root / "memory" / "short" / "sase.md").read_text()
    assert "`core`: Local Rust core." in project_memory
    assert "`github`: Global GitHub plugin." not in project_memory
    assert "../local-core" not in project_memory
    assert "`github`: Global GitHub plugin." in home_memory
    assert "`core`: Local Rust core." not in home_memory
    assert "/global/github" not in home_memory

    sibling_trigger = (
        "When you need to make changes to files in a numbered-workspace sibling "
        "repository or need to review numbered-workspace sibling repository code, "
        "agents MUST run:"
    )
    for memory in (project_memory, home_memory):
        assert sibling_trigger in _single_line(memory)
        assert "sibling reads/writes" in memory
        assert "When a sibling repository needs changes, agents MUST run:" not in memory
        assert "sibling edits" not in memory

    for root in (project_root, home_root):
        assert (root / "memory" / "long").is_dir()
        assert (root / "memory" / "README.md").is_file()
        readme = (root / "memory" / "README.md").read_text()
        assert "`sase memory list`" in readme
        assert "`sase memory init`" in readme
        assert "`@memory/...` reference" in readme
        assert "Plain `memory/...` mentions" in readme
        assert "`.sase/memory/` are prompt-dependent" in readme
        assert "@memory/short/sase.md" in (root / "AGENTS.md").read_text()
        for filename in ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md"):
            assert (root / filename).read_text() == "@AGENTS.md\n"


def test_init_memory_static_siblings_use_paths_without_workspace_open(
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
sibling_repos:
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

    project_memory = (project_root / "memory" / "short" / "sase.md").read_text()
    single_line = _single_line(project_memory)
    assert "Static-path sibling repositories (`workspace.strategy: none`)" not in (
        project_memory
    )
    assert (
        "- `dotfiles`: User dotfiles source. This repo is defined in the "
        "`$STATIC_ONE/` directory."
    ) in single_line
    assert (
        "- `notes`: Static notes checkout. This repo is defined in the "
        "`../static-two/` directory."
    ) in single_line
    assert "sase workspace open -p <sibling_repo> <workspace_num>" not in project_memory


def test_init_memory_mixed_siblings_render_static_location_and_workspace_open(
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
    description: Numbered Rust core checkout.
  - name: dotfiles
    path: ../dotfiles
    description: Static dotfiles source.
    workspace:
      strategy: none
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "short" / "sase.md").read_text()
    single_line = _single_line(project_memory)
    assert "Static-path sibling repositories (`workspace.strategy: none`)" not in (
        project_memory
    )
    assert (
        "- `dotfiles`: Static dotfiles source. This repo is defined in the "
        "`../dotfiles/` directory."
    ) in single_line
    assert "numbered-workspace sibling repository" in project_memory
    assert "sase workspace open -p <sibling_repo> <workspace_num>" in project_memory
    assert "numbered-workspace sibling reads/writes" in single_line


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
sibling_repos:
  - name: shared
    path: ../shared
    description: Static shared checkout.
    workspace:
      strategy: none
""",
    )

    assert run_handler() == 0

    project_memory = (project_root / "memory" / "short" / "sase.md").read_text()
    assert (
        "- `shared`: Static shared checkout. This repo is defined in the "
        "`../shared/` directory."
    ) in _single_line(project_memory)
    assert str((tmp_path / "primary" / "shared").resolve(strict=False)) not in (
        project_memory
    )
    assert str(numbered_relative_path.resolve(strict=False)) not in project_memory
    assert "sase workspace open -p <sibling_repo> <workspace_num>" not in project_memory


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

    project_memory = (project_root / "memory" / "short" / "sase.md").read_text()
    home_memory = (home_root / "memory" / "short" / "sase.md").read_text()
    assert project_memory.startswith("# SASE = Structured Agentic Software Engineering")
    assert "## Ephemeral `project_<N>` Workspace Directories" in project_memory
    assert "full clones of the project repo" in project_memory
    assert "directories are named `project_<N>`" in project_memory
    assert "sase workspace open -p <sibling_repo> <workspace_num>" not in project_memory
    assert "sase workspace open -p <sibling_repo> <workspace_num>" not in home_memory
    assert "{{ project }}" not in project_memory
    assert "Ephemeral" not in home_memory
    assert home_memory.startswith("# SASE Memory")


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

    project_memory = (project_root / "memory" / "short" / "sase.md").read_text()
    assert "## Ephemeral `project_<N>` Workspace Directories" in project_memory
    assert "full clones of the project repo" in project_memory
    assert "project_10_<N>" not in project_memory


def test_init_memory_reports_missing_sibling_descriptions(
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

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "cannot generate project memory" in err
    assert "field 'description'" in err
    assert not (project_root / "memory").exists()


def test_init_memory_overwrites_provider_shims(
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
    write(project_root / "AGENTS.md", "@memory/short/sase.md\n")
    write(project_root / "CLAUDE.md", "old instructions\n")

    assert run_handler() == 0

    assert (project_root / "CLAUDE.md").read_text() == "@AGENTS.md\n"
    for filename in ("GEMINI.md", "QWEN.md", "OPENCODE.md"):
        assert (project_root / filename).read_text() == "@AGENTS.md\n"


def test_init_memory_allows_transitive_memory_references(
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
        "@memory/short/sase.md\n\nmemory/long/index.md\n",
    )
    write(
        project_root / "memory" / "long" / "index.md",
        "# Index\n\n@memory/long/detail.md\n",
    )
    write(project_root / "memory" / "long" / "detail.md", "# Detail\n")

    assert run_handler() == 0


def test_init_memory_rejects_unreferenced_memory_files(
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
    write(project_root / "AGENTS.md", "@memory/short/sase.md\n")
    write(
        project_root / "memory" / "long" / "orphan.md",
        "# Orphan\n\n@memory/long/orphan.md\n",
    )

    assert run_handler() == 1
    err = capsys.readouterr().err
    assert "unreferenced memory files" in err
    assert "memory/long/orphan.md" in err


def test_init_memory_plan_empty_after_prettier_formats_generated_files(
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
    description: Shared Rust core backend for SASE domain behavior and cross-frontend APIs.
""",
    )

    assert run_memory() == 0

    generated = [
        project_root / "memory" / "short" / "sase.md",
        project_root / "memory" / "README.md",
        home_root / "memory" / "short" / "sase.md",
        home_root / "memory" / "README.md",
    ]
    before = {path: path.read_text(encoding="utf-8") for path in generated}
    result = subprocess.run(
        [
            *_prettier_command(),
            "--write",
            "--prose-wrap=always",
            "--print-width=120",
            *[str(path) for path in generated],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"prettier --write failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert {path: path.read_text(encoding="utf-8") for path in generated} == before

    plan = plan_memory()
    assert plan.actions == ()
    assert plan.blockers == ()


def test_init_memory_generated_markdown_passes_prettier_check(
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

    generated = [
        project_root / "memory" / "short" / "sase.md",
        project_root / "memory" / "README.md",
    ]
    assert all(path.read_bytes().endswith(b"\n") for path in generated)
    result = subprocess.run(
        [
            *_prettier_command(),
            "--check",
            "--prose-wrap=always",
            "--print-width=120",
            *[str(path) for path in generated],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"prettier --check failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )

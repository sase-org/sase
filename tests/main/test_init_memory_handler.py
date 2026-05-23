"""Tests for the ``sase init memory`` command."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.main import init_memory_handler
from sase.main.init_memory_handler import handle_init_memory_command


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_handler(*, no_commit: bool = True) -> int:
    with pytest.raises(SystemExit) as exc:
        handle_init_memory_command(argparse.Namespace(no_commit=no_commit))
    return int(exc.value.code)


def _patch_standard_paths(
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_root: Path,
    home_root: Path,
    config_dir: Path,
    use_chezmoi: bool = False,
) -> None:
    monkeypatch.chdir(project_root)
    monkeypatch.setenv("HOME", str(home_root))
    monkeypatch.setattr(init_memory_handler, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(init_memory_handler, "get_use_chezmoi", lambda: use_chezmoi)


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
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    _write(
        project_root / "sase.yml",
        """
sibling_repos:
  - name: core
    path: ../local-core
    description: Local Rust core.
""",
    )
    _write(
        config_dir / "sase.yml",
        """
sibling_repos:
  - name: github
    path: /global/github
    description: Global GitHub plugin.
""",
    )

    assert _run_handler() == 0
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

    for root in (project_root, home_root):
        assert (root / "memory" / "long").is_dir()
        assert (root / "memory" / "README.md").is_file()
        assert "@memory/short/sase.md" in (root / "AGENTS.md").read_text()
        for filename in ("CLAUDE.md", "GEMINI.md", "QWEN.md", "OPENCODE.md"):
            assert (root / filename).read_text() == "@AGENTS.md\n"


def test_init_memory_project_memory_includes_workspace_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )

    assert _run_handler() == 0

    project_memory = (project_root / "memory" / "short" / "sase.md").read_text()
    home_memory = (home_root / "memory" / "short" / "sase.md").read_text()
    assert project_memory.startswith("# SASE = Structured Agentic Software Engineering")
    assert "## Ephemeral `project_<N>` Workspace Directories" in project_memory
    assert "full clones of the project repo" in project_memory
    assert "directories are named `project_<N>`" in project_memory
    assert (
        "assigned to the primary repo (check what directory you were started in "
        "to figure this out)"
    ) in project_memory
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
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    _write(
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

    assert _run_handler() == 0

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
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    _write(
        project_root / "sase.yml",
        """
sibling_repos:
  - name: core
    path: ../sase-core
""",
    )

    assert _run_handler() == 1
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
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    _write(project_root / "AGENTS.md", "@memory/short/sase.md\n")
    _write(project_root / "CLAUDE.md", "old instructions\n")

    assert _run_handler() == 0

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
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    _write(
        project_root / "AGENTS.md",
        "@memory/short/sase.md\n\nmemory/long/index.md\n",
    )
    _write(
        project_root / "memory" / "long" / "index.md",
        "# Index\n\n@memory/long/detail.md\n",
    )
    _write(project_root / "memory" / "long" / "detail.md", "# Detail\n")

    assert _run_handler() == 0


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
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    _write(project_root / "AGENTS.md", "@memory/short/sase.md\n")
    _write(
        project_root / "memory" / "long" / "orphan.md",
        "# Orphan\n\n@memory/long/orphan.md\n",
    )

    assert _run_handler() == 1
    err = capsys.readouterr().err
    assert "unreferenced memory files" in err
    assert "memory/long/orphan.md" in err


def test_init_memory_uses_chezmoi_home_and_global_config_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    chezmoi_home = tmp_path / "chezmoi" / "home"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
        use_chezmoi=True,
    )
    monkeypatch.setattr(init_memory_handler, "CHEZMOI_HOME", chezmoi_home)
    _write(
        chezmoi_home / "dot_config" / "sase" / "sase.yml",
        """
sibling_repos:
  - name: telegram
    path: /global/telegram
    description: Telegram workflow plugin.
""",
    )

    deployed: list[Path] = []

    def fake_deploy(paths: Iterable[Path]) -> int:
        deployed.extend(paths)
        return 0

    monkeypatch.setattr(init_memory_handler, "_deploy_to_chezmoi", fake_deploy)

    assert _run_handler() == 0

    assert not (home_root / "memory").exists()
    chezmoi_memory = (chezmoi_home / "memory" / "short" / "sase.md").read_text()
    assert "`telegram`: Telegram workflow plugin." in chezmoi_memory
    assert "/global/telegram" not in chezmoi_memory
    assert chezmoi_home / "memory" / "short" / "sase.md" in deployed


def test_init_memory_default_commits_and_pushes_project_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    monkeypatch.setattr(
        init_memory_handler, "_project_memory_name", lambda root: "project"
    )

    git_calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
        cmd: list[str] = args[0] if args else kwargs.get("cmd", [])
        git_calls.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=f"{project_root}\n", stderr="")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        if "commit" in cmd:
            return MagicMock(
                returncode=0,
                stdout="[main abc1234] chore: run sase init memory\n",
                stderr="",
            )
        if "pull" in cmd:
            return MagicMock(returncode=0, stdout="Already up to date.\n", stderr="")
        if "push" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="To origin\n")
        return MagicMock(returncode=0, stdout="", stderr="")

    precommit_calls: list[str] = []

    def fake_precommit(cwd: str) -> bool:
        precommit_calls.append(cwd)
        return True

    monkeypatch.setattr(init_memory_handler, "run_precommit", fake_precommit)
    monkeypatch.setattr(init_memory_handler.subprocess, "run", fake_run)

    assert _run_handler(no_commit=False) == 0

    assert precommit_calls == [str(project_root)]
    verbs = [cmd[cmd.index("git") + 3] for cmd in git_calls if cmd[0] == "git"]
    assert verbs == [
        "rev-parse",
        "add",
        "add",
        "add",
        "add",
        "add",
        "add",
        "add",
        "diff",
        "commit",
        "pull",
        "push",
    ]
    commit_calls = [cmd for cmd in git_calls if "commit" in cmd and "-m" in cmd]
    assert commit_calls
    message = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert message == "chore: run sase init memory"


def test_init_memory_no_commit_skips_project_deploy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    monkeypatch.setattr(
        init_memory_handler, "_project_memory_name", lambda root: "project"
    )

    precommit = MagicMock(return_value=True)
    git_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(init_memory_handler, "run_precommit", precommit)
    monkeypatch.setattr(init_memory_handler.subprocess, "run", git_run)

    assert _run_handler(no_commit=True) == 0
    precommit.assert_not_called()
    git_run.assert_not_called()


def test_init_memory_failing_precommit_aborts_project_deploy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    _patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    monkeypatch.setattr(
        init_memory_handler, "_project_memory_name", lambda root: "project"
    )

    git_calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
        cmd: list[str] = args[0] if args else kwargs.get("cmd", [])
        git_calls.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=f"{project_root}\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(init_memory_handler, "run_precommit", lambda cwd: False)
    monkeypatch.setattr(init_memory_handler.subprocess, "run", fake_run)

    assert _run_handler(no_commit=False) == 1

    assert [cmd[cmd.index("git") + 3] for cmd in git_calls] == ["rev-parse"]

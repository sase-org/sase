"""Tests for ``sase memory init`` project commit behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.main import init_memory_handler
from sase.main.init_memory.git_state import DirtyPath, PreInitGitState
from sase.main.init_memory.models import MemoryRootResult
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    run_handler,
    short_note,
    write,
)

_PROJECT_DETECTION_COMMAND = ["git", "config", "--get", "remote.origin.url"]


def _prepare_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
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
    monkeypatch.setattr(
        init_memory_handler, "_project_memory_name", lambda root: "project"
    )
    return project_root, home_root, config_dir


def _install_successful_git(
    monkeypatch: pytest.MonkeyPatch,
    project_root: Path,
    *,
    status_stdout: bytes = b"",
) -> list[list[str]]:
    git_calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
        cmd: list[str] = args[0] if args else kwargs.get("cmd", [])
        git_calls.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=f"{project_root}\n", stderr="")
        if "status" in cmd:
            return MagicMock(returncode=0, stdout=status_stdout, stderr=b"")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        if "commit" in cmd:
            message = cmd[cmd.index("-m") + 1]
            subject = message.splitlines()[0]
            return MagicMock(
                returncode=0,
                stdout=f"[main abc1234] {subject}\n",
                stderr="",
            )
        if "pull" in cmd:
            return MagicMock(returncode=0, stdout="Already up to date.\n", stderr="")
        if "push" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="To origin\n")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(init_memory_handler.subprocess, "run", fake_run)
    return git_calls


def _without_project_detection(calls: list[list[str]]) -> list[list[str]]:
    return [cmd for cmd in calls if cmd != _PROJECT_DETECTION_COMMAND]


def test_init_memory_default_commits_and_pushes_project_changes(
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
    monkeypatch.setattr(
        init_memory_handler, "_project_memory_name", lambda root: "project"
    )

    git_calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
        cmd: list[str] = args[0] if args else kwargs.get("cmd", [])
        git_calls.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=f"{project_root}\n", stderr="")
        if "status" in cmd:
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
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

    assert run_handler(no_commit=False) == 0

    assert precommit_calls == [str(project_root)]
    deploy_git_calls = _without_project_detection(git_calls)
    verbs = [cmd[cmd.index("git") + 3] for cmd in deploy_git_calls if cmd[0] == "git"]
    assert verbs == [
        "rev-parse",
        "status",
        "add",
        "add",
        "add",
        "add",
        "add",
        "add",
        "add",
        "add",
        "diff",
        "commit",
        "rev-parse",
        "pull",
        "push",
    ]
    add_paths = [
        Path(cmd[-1])
        for cmd in deploy_git_calls
        if cmd[0] == "git" and cmd[cmd.index("git") + 3] == "add"
    ]
    assert project_root / "memory" / "assets" / "memory-directory-map.png" in add_paths
    commit_calls = [cmd for cmd in git_calls if "commit" in cmd and "-m" in cmd]
    assert commit_calls
    message = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert message == "chore: run sase init memory\n\nSASE_TYPE=memory"


def test_enable_project_memory_stages_created_local_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _prepare_project(tmp_path, monkeypatch)
    (project_root / "sase.yml").unlink()
    git_calls = _install_successful_git(monkeypatch, project_root)
    monkeypatch.setattr(init_memory_handler, "run_precommit", lambda cwd: True)

    assert run_handler(no_commit=False, enable_project_memory=True) == 0

    assert any(
        "add" in cmd and Path(cmd[-1]) == project_root / "sase.yml" for cmd in git_calls
    )


def test_init_memory_no_upstream_commits_and_skips_pull_push(
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
    monkeypatch.setattr(
        init_memory_handler, "_project_memory_name", lambda root: "project"
    )

    git_calls: list[list[str]] = []

    def fake_run(*args: Any, **kwargs: Any) -> MagicMock:
        cmd: list[str] = args[0] if args else kwargs.get("cmd", [])
        git_calls.append(cmd)
        if "@{u}" in cmd:
            return MagicMock(returncode=128, stdout="", stderr="no upstream")
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout=f"{project_root}\n", stderr="")
        if "status" in cmd:
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        if "commit" in cmd:
            return MagicMock(
                returncode=0,
                stdout="[main abc1234] chore: run sase init memory\n",
                stderr="",
            )
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(init_memory_handler, "run_precommit", lambda cwd: True)
    monkeypatch.setattr(init_memory_handler.subprocess, "run", fake_run)

    assert run_handler(no_commit=False) == 0

    deploy_git_calls = _without_project_detection(git_calls)
    assert any("commit" in cmd for cmd in deploy_git_calls)
    assert any("@{u}" in cmd for cmd in deploy_git_calls)
    assert not any("pull" in cmd for cmd in deploy_git_calls)
    assert not any("push" in cmd for cmd in deploy_git_calls)
    assert "init memory: no upstream configured; skipping pull/push" in (
        capsys.readouterr().out
    )


def test_init_memory_no_commit_skips_project_deploy(
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
    monkeypatch.setattr(
        init_memory_handler, "_project_memory_name", lambda root: "project"
    )

    precommit = MagicMock(return_value=True)
    git_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(init_memory_handler, "run_precommit", precommit)
    monkeypatch.setattr(init_memory_handler.subprocess, "run", git_run)

    assert run_handler(no_commit=True) == 0
    precommit.assert_not_called()
    assert (
        _without_project_detection([call.args[0] for call in git_run.call_args_list])
        == []
    )


def test_init_memory_folds_memory_dirty_with_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _prepare_project(tmp_path, monkeypatch)
    write(
        project_root / "memory" / "obsidian.md",
        short_note("# Obsidian\n\nObsidian vault workflow."),
    )
    git_calls = _install_successful_git(
        monkeypatch,
        project_root,
        status_stdout=b" M memory/obsidian.md\0",
    )

    precommit_calls: list[str] = []
    monkeypatch.setattr(
        init_memory_handler,
        "run_precommit",
        lambda cwd: not precommit_calls.append(cwd),
    )

    assert (
        run_handler(
            no_commit=False,
            message="document obsidian vault workflow",
        )
        == 0
    )

    assert precommit_calls == [str(project_root)]
    assert any(
        "add" in cmd and cmd[-1].endswith("memory/obsidian.md") for cmd in git_calls
    )
    commit_calls = [cmd for cmd in git_calls if "commit" in cmd and "-m" in cmd]
    message = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert (
        message == "docs(memory): document obsidian vault workflow\n\nSASE_TYPE=memory"
    )


def test_init_memory_folds_memory_dirty_preserves_conventional_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _prepare_project(tmp_path, monkeypatch)
    write(
        project_root / "memory" / "new_note.md",
        short_note("# New Memory\n\nNew memory."),
    )
    git_calls = _install_successful_git(
        monkeypatch,
        project_root,
        status_stdout=b"A  memory/new_note.md\0",
    )
    monkeypatch.setattr(init_memory_handler, "run_precommit", lambda cwd: True)

    assert (
        run_handler(
            no_commit=False,
            message="feat(memory): add obsidian note",
        )
        == 0
    )

    commit_calls = [cmd for cmd in git_calls if "commit" in cmd and "-m" in cmd]
    message = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert message == "feat(memory): add obsidian note\n\nSASE_TYPE=memory"


def test_init_memory_folds_memory_dirty_with_tty_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _prepare_project(tmp_path, monkeypatch)
    write(
        project_root / "memory" / "obsidian.md",
        short_note("# Obsidian\n\nObsidian vault workflow."),
    )
    git_calls = _install_successful_git(
        monkeypatch,
        project_root,
        status_stdout=b" M memory/obsidian.md\0",
    )
    monkeypatch.setattr(init_memory_handler, "run_precommit", lambda cwd: True)
    monkeypatch.setattr(init_memory_handler, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "document obsidian vault workflow")

    assert run_handler(no_commit=False) == 0

    commit_calls = [cmd for cmd in git_calls if "commit" in cmd and "-m" in cmd]
    message = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert (
        message == "docs(memory): document obsidian vault workflow\n\nSASE_TYPE=memory"
    )


def test_init_memory_memory_dirty_non_tty_without_message_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _prepare_project(tmp_path, monkeypatch)
    write(
        project_root / "memory" / "obsidian.md",
        short_note("# Obsidian\n\nObsidian vault workflow."),
    )
    git_calls = _install_successful_git(
        monkeypatch,
        project_root,
        status_stdout=b" M memory/obsidian.md\0",
    )
    precommit = MagicMock(return_value=True)
    monkeypatch.setattr(init_memory_handler, "run_precommit", precommit)
    monkeypatch.setattr(init_memory_handler, "_stdin_is_tty", lambda: False)

    assert run_handler(no_commit=False) == 1

    precommit.assert_not_called()
    assert not any("add" in cmd for cmd in git_calls)
    assert not any("commit" in cmd for cmd in git_calls)


def test_init_memory_memory_dirty_empty_prompt_aborts_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _prepare_project(tmp_path, monkeypatch)
    write(
        project_root / "memory" / "obsidian.md",
        short_note("# Obsidian\n\nObsidian vault workflow."),
    )
    git_calls = _install_successful_git(
        monkeypatch,
        project_root,
        status_stdout=b" M memory/obsidian.md\0",
    )
    monkeypatch.setattr(init_memory_handler, "run_precommit", MagicMock())
    monkeypatch.setattr(init_memory_handler, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "")

    assert run_handler(no_commit=False) == 1

    assert not any("add" in cmd for cmd in git_calls)
    assert not any("commit" in cmd for cmd in git_calls)


def test_init_memory_memory_dirty_eof_prompt_aborts_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _prepare_project(tmp_path, monkeypatch)
    write(
        project_root / "memory" / "obsidian.md",
        short_note("# Obsidian\n\nObsidian vault workflow."),
    )
    git_calls = _install_successful_git(
        monkeypatch,
        project_root,
        status_stdout=b" M memory/obsidian.md\0",
    )
    monkeypatch.setattr(init_memory_handler, "run_precommit", MagicMock())
    monkeypatch.setattr(init_memory_handler, "_stdin_is_tty", lambda: True)

    def raise_eof() -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    assert run_handler(no_commit=False) == 1

    assert not any("add" in cmd for cmd in git_calls)
    assert not any("commit" in cmd for cmd in git_calls)


def test_init_memory_foreign_dirty_refuses_without_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, _home_root, _config_dir = _prepare_project(tmp_path, monkeypatch)
    git_calls = _install_successful_git(
        monkeypatch,
        project_root,
        status_stdout=b" M src/sase/foo.py\0",
    )
    precommit = MagicMock(return_value=True)
    monkeypatch.setattr(init_memory_handler, "run_precommit", precommit)

    assert run_handler(no_commit=False) == 1

    assert (project_root / "AGENTS.md").exists()
    precommit.assert_not_called()
    assert not any("add" in cmd for cmd in git_calls)
    assert not any("commit" in cmd for cmd in git_calls)


def test_init_memory_foreign_dirty_without_init_changes_is_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    git_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    precommit = MagicMock(return_value=True)
    monkeypatch.setattr(init_memory_handler.subprocess, "run", git_run)
    monkeypatch.setattr(init_memory_handler, "run_precommit", precommit)

    result = MemoryRootResult(
        root=project_root,
        written_paths=(),
        deleted_paths=(),
        unreferenced=(),
    )
    git_state = PreInitGitState(
        git_root=project_root,
        memory_dirty=(),
        other_dirty=(DirtyPath(path="src/sase/foo.py", status=" M"),),
    )

    assert (
        init_memory_handler._deploy_to_project_repo(
            result,
            no_commit=False,
            git_state=git_state,
        )
        == 0
    )
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
    patch_standard_paths(
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
        if "status" in cmd:
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(init_memory_handler, "run_precommit", lambda cwd: False)
    monkeypatch.setattr(init_memory_handler.subprocess, "run", fake_run)

    assert run_handler(no_commit=False) == 1

    deploy_git_calls = _without_project_detection(git_calls)
    assert [cmd[cmd.index("git") + 3] for cmd in deploy_git_calls] == [
        "rev-parse",
        "status",
    ]

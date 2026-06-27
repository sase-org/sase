"""Tests for ``sase memory init`` project commit behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.main import init_memory_handler
from tests.main.init_memory_handler_helpers import patch_standard_paths, run_handler


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
    assert message == "chore: run sase init memory\n\nSASE_TYPE=memory"


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
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(init_memory_handler, "run_precommit", lambda cwd: False)
    monkeypatch.setattr(init_memory_handler.subprocess, "run", fake_run)

    assert run_handler(no_commit=False) == 1

    assert [cmd[cmd.index("git") + 3] for cmd in git_calls] == ["rev-parse"]

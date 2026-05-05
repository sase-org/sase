"""Tests for the ``sase init-skills`` chezmoi auto-deploy path."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.main import init_skills_handler
from sase.main.init_skills_handler import _deploy_to_chezmoi
from tests.main.init_skills_handler_helpers import git_cmd_handler, make_args


def test_deploy_happy_path_runs_full_sequence() -> None:
    """add -> commit -> pull -> push -> chezmoi apply in order."""
    args = make_args()
    paths = [Path("/home/x/chezmoi/home/dot_claude/skills/foo/SKILL.md")]

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=git_cmd_handler(),
    ) as mock_run:
        rc = _deploy_to_chezmoi(paths, args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    verbs = [cmd[cmd.index("git") + 3] if cmd[0] == "git" else cmd[0] for cmd in calls]
    assert verbs == ["rev-parse", "add", "diff", "commit", "pull", "push", "chezmoi"]


def test_deploy_no_commit_skips_everything() -> None:
    """--no-commit: handler returns immediately without running anything."""
    args = make_args(no_commit=True)

    with patch.object(init_skills_handler.subprocess, "run") as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    mock_run.assert_not_called()


def test_deploy_no_push_stops_after_commit() -> None:
    """--no-push: stage + commit, but no pull/push/apply."""
    args = make_args(no_push=True)

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=git_cmd_handler(),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    commands = [
        cmd[cmd.index("git") + 3] if cmd[0] == "git" else cmd[0] for cmd in calls
    ]
    assert commands == ["rev-parse", "add", "diff", "commit"]


def test_deploy_no_apply_stops_after_push() -> None:
    """--no-apply: run through push but skip chezmoi apply."""
    args = make_args(no_apply=True)

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=git_cmd_handler(),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert all(cmd[0] != "chezmoi" for cmd in calls)
    assert any("push" in cmd for cmd in calls)


def test_deploy_nothing_staged_skips_commit_and_later_steps() -> None:
    """If git diff --cached --quiet returns 0, no commit/push/apply."""
    args = make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=git_cmd_handler(nothing_staged=True),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any("commit" in cmd for cmd in calls)
    assert not any("push" in cmd for cmd in calls)
    assert not any(cmd[0] == "chezmoi" for cmd in calls)


def test_deploy_not_a_git_repo_skips_gracefully(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """git rev-parse --show-toplevel failure -> warn and return 0."""
    args = make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=git_cmd_handler(repo_check_rc=1),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert len(calls) == 1
    assert "rev-parse" in calls[0]
    err = capsys.readouterr().err
    assert "not a git repo" in err


def test_deploy_git_missing_skips_gracefully(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If git binary is missing on repo check, skip with warning."""
    args = make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=git_cmd_handler(repo_check_raises=FileNotFoundError),
    ):
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    assert "git not found" in capsys.readouterr().err


def test_deploy_push_failure_returns_nonzero_and_skips_apply(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Push failure: no chezmoi apply, non-zero exit, stderr has reason."""
    args = make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=git_cmd_handler(push_rc=1),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 1
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any(cmd[0] == "chezmoi" for cmd in calls)
    assert "push failed" in capsys.readouterr().err


def test_deploy_pull_failure_returns_nonzero_and_skips_push(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Pull failure: no push, no apply, non-zero exit."""
    args = make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=git_cmd_handler(pull_rc=1),
    ) as mock_run:
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 1
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any("push" in cmd for cmd in calls)
    assert not any(cmd[0] == "chezmoi" for cmd in calls)
    assert "pull failed" in capsys.readouterr().err


def test_deploy_chezmoi_missing_warns_but_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """chezmoi binary missing -> warning and exit 0 (git side succeeded)."""
    args = make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=git_cmd_handler(apply_raises=FileNotFoundError),
    ):
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 0
    assert "chezmoi not found" in capsys.readouterr().err


def test_deploy_chezmoi_apply_failure_returns_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """chezmoi apply failure (non-zero exit) surfaces as non-zero return."""
    args = make_args()

    with patch.object(
        init_skills_handler.subprocess,
        "run",
        side_effect=git_cmd_handler(apply_rc=1),
    ):
        rc = _deploy_to_chezmoi([Path("/x/a")], args)

    assert rc == 1
    assert "chezmoi apply failed" in capsys.readouterr().err


def test_deploy_provider_filter_in_commit_message() -> None:
    """--provider=claude -> commit message mentions provider."""
    args = make_args(provider="claude")
    captured: list[list[str]] = []

    def handler(*a: Any, **kw: Any) -> MagicMock:
        cmd = a[0] if a else kw.get("cmd", [])
        captured.append(cmd)
        if "rev-parse" in cmd:
            return MagicMock(returncode=0, stdout="", stderr="")
        if "diff" in cmd and "--cached" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(init_skills_handler.subprocess, "run", side_effect=handler):
        _deploy_to_chezmoi([Path("/x/a")], args)

    commit_calls = [c for c in captured if "commit" in c and "-m" in c]
    assert commit_calls, "No commit call observed"
    msg = commit_calls[0][commit_calls[0].index("-m") + 1]
    assert "claude" in msg

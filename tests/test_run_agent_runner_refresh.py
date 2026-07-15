"""Tests for refreshing stale runner code after dependency waits."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_refresh import (
    RUNNER_CODE_REFRESHED_ENV,
    _source_code_identity,
    refresh_runner_code_after_wait,
)
from sase.version._models import GitProbeResult, GitVersionMetadata


def _git_result(commit: str) -> GitProbeResult:
    return GitProbeResult(
        GitVersionMetadata(
            root="/repo",
            commit=commit,
            short_commit=commit[:9],
            tag=None,
            distance=None,
            dirty=False,
        )
    )


def test_source_code_identity_tracks_head_changes() -> None:
    checkout = Path("/repo")
    old = "a" * 40
    new = "b" * 40
    with patch(
        "sase.axe.run_agent_runner_refresh.probe_git_metadata_at_ref",
        side_effect=[_git_result(old), _git_result(old), _git_result(new)],
    ):
        assert _source_code_identity(checkout) == old
        assert _source_code_identity(checkout) == old
        assert _source_code_identity(checkout) == new


def test_source_code_identity_is_inert_without_git_metadata() -> None:
    with patch(
        "sase.axe.run_agent_runner_refresh.probe_git_metadata_at_ref",
        return_value=GitProbeResult(None, "not a git checkout"),
    ):
        assert _source_code_identity(Path("/wheel")) is None
    assert _source_code_identity(None) is None


def test_changed_identity_reexecs_original_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    old = "a" * 40
    new = "b" * 40
    prompt_file = tmp_path / "submitted-prompt.md"
    submitted_xprompt = "%n(fix)\nKeep this exact prompt\n"

    def assert_exec_handoff(*_args: object) -> None:
        assert prompt_file.read_text(encoding="utf-8") == submitted_xprompt
        assert os.environ[RUNNER_CODE_REFRESHED_ENV] == "1"

    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value=new,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=assert_exec_handoff,
        ) as execv,
        patch.object(sys, "executable", "/venv/bin/python"),
        patch.object(sys, "argv", ["runner.py", "--workspace-num", "7"]),
    ):
        refresh_runner_code_after_wait(
            old,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt=submitted_xprompt,
        )

    execv.assert_called_once_with(
        "/venv/bin/python",
        ["/venv/bin/python", "runner.py", "--workspace-num", "7"],
    )
    assert os.environ[RUNNER_CODE_REFRESHED_ENV] == "1"


def test_prompt_rewrite_failure_skips_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    prompt_file = tmp_path / "missing" / "prompt.md"
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="prompt",
        )

    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ
    assert "Skipping sase runner code refresh" in capsys.readouterr().err


def test_exec_failure_continues_without_refresh_guard_or_prompt_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    prompt_file = tmp_path / "prompt.md"
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value="b" * 40,
        ),
        patch(
            "sase.axe.run_agent_runner_refresh.os.execv",
            side_effect=OSError("exec failed"),
        ),
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file=str(prompt_file),
            submitted_xprompt="prompt",
        )

    assert RUNNER_CODE_REFRESHED_ENV not in os.environ
    assert not prompt_file.exists()
    assert "continuing: exec failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("startup_identity", "current_identity", "blocked", "killed"),
    [
        ("a" * 40, "a" * 40, True, False),
        ("a" * 40, "b" * 40, False, False),
        ("a" * 40, "b" * 40, True, True),
        (None, "b" * 40, True, False),
    ],
    ids=("unchanged", "no-blocking-wait", "killed", "unknown-startup"),
)
def test_refresh_is_inert_without_all_preconditions(
    monkeypatch: pytest.MonkeyPatch,
    startup_identity: str | None,
    current_identity: str,
    blocked: bool,
    killed: bool,
) -> None:
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity",
            return_value=current_identity,
        ),
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            startup_identity,
            blocking_wait_occurred=blocked,
            killed=killed,
            prompt_file="/tmp/prompt.md",
            submitted_xprompt="prompt",
        )

    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ


def test_refreshed_guard_prevents_loop_and_is_not_inherited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(RUNNER_CODE_REFRESHED_ENV, "1")
    with (
        patch(
            "sase.axe.run_agent_runner_refresh.runner_code_identity"
        ) as current_identity,
        patch("sase.axe.run_agent_runner_refresh.os.execv") as execv,
    ):
        refresh_runner_code_after_wait(
            "a" * 40,
            blocking_wait_occurred=True,
            killed=False,
            prompt_file="/tmp/prompt.md",
            submitted_xprompt="prompt",
        )

    current_identity.assert_not_called()
    execv.assert_not_called()
    assert RUNNER_CODE_REFRESHED_ENV not in os.environ

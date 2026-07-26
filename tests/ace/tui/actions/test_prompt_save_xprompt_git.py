"""Git commit and push behavior for saved xprompts and snippets."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt import (
    _run_git_commit_push_sync,
)
from sase.ace.tui.modals import ConfirmActionModal

from ._prompt_save_xprompt_helpers import _CommitHarness


def test_commit_push_confirmation_submits_tracked_task(tmp_path: Path) -> None:
    path = tmp_path / "xprompts" / "review.md"
    path.parent.mkdir()
    path.write_text("body", encoding="utf-8")
    harness = _CommitHarness()
    with (
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.get_git_root",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.has_git_changes",
            return_value=True,
        ),
    ):
        harness._offer_git_commit(str(path), is_new=True, xprompt_name="review")
        confirm, callback = harness.pushed[0]
        assert isinstance(confirm, ConfirmActionModal)
        assert callable(callback)
        callback(True)
    assert len(harness.submitted) == 1
    args, kwargs = harness.submitted[0]
    assert args[:3] == ("xprompt-commit", "xprompts/review.md", str(tmp_path))
    assert kwargs["dedup_key"] == f"xprompt-commit:{tmp_path}:xprompts/review.md"


def test_successful_snippet_commit_refreshes_config_catalog(tmp_path: Path) -> None:
    path = tmp_path / "sase.yml"
    path.write_text("ace: {}\n", encoding="utf-8")
    harness = _CommitHarness()
    with (
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.get_git_root",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.has_git_changes",
            return_value=True,
        ),
    ):
        harness._offer_git_commit(
            str(path),
            is_new=False,
            xprompt_name="review",
            noun="snippet",
            commit_type="snippet",
        )
        _confirm, callback = harness.pushed[0]
        assert callable(callback)
        callback(True)

    on_complete = harness.submitted[0][1]["on_complete"]
    assert callable(on_complete)
    on_complete(
        SimpleNamespace(
            success=True,
            message="Committed and pushed; applied chezmoi changes",
            payload=False,
        )
    )

    assert harness.config_refreshes == ["snippet_commit_apply"]


def test_failed_or_skipped_snippet_commit_does_not_refresh_catalog(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sase.yml"
    path.write_text("ace: {}\n", encoding="utf-8")
    harness = _CommitHarness()
    with (
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.get_git_root",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.has_git_changes",
            return_value=True,
        ),
    ):
        harness._offer_git_commit(
            str(path),
            is_new=False,
            xprompt_name="review",
            noun="snippet",
            commit_type="snippet",
        )
        _confirm, callback = harness.pushed[0]
        assert callable(callback)
        callback(False)
        assert harness.submitted == []

        callback(True)

    on_complete = harness.submitted[0][1]["on_complete"]
    assert callable(on_complete)
    on_complete(
        SimpleNamespace(success=False, message="chezmoi apply failed", payload=False)
    )

    assert harness.config_refreshes == []


def test_git_commit_push_worker_runs_git_sequence(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    path = tmp_path / "review.md"
    with (
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
            side_effect=run,
        ),
        patch("sase.config.get_use_chezmoi", return_value=False),
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert result.success is True
    assert calls[-3:] == [
        ["git", "-C", str(tmp_path), "commit", "-m", "chore: Add xprompt review"],
        ["git", "-C", str(tmp_path), "pull", "--rebase"],
        ["git", "-C", str(tmp_path), "push"],
    ]


def test_git_commit_push_worker_stops_on_add_failure(tmp_path: Path) -> None:
    path = tmp_path / "review.md"
    with patch(
        "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
        return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="pathspec"),
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )
    assert result.success is False
    assert result.message == "Git add failed: pathspec"


def test_git_commit_push_worker_backs_off_then_removes_stale_index_lock(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    commit_attempts = 0

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal commit_attempts
        if argv[3] == "commit":
            commit_attempts += 1
            if lock.exists():
                return subprocess.CompletedProcess(
                    argv,
                    128,
                    stdout="",
                    stderr=f"fatal: Unable to create '{lock}': File exists.",
                )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with (
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
            side_effect=run,
        ),
        patch("sase.git_lock_retry.git_lock_retry_delays", return_value=(0.001, 0.001)),
        patch("sase.config.get_use_chezmoi", return_value=False),
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(tmp_path / "review.md"),
            commit_message="chore: Add xprompt review",
        )
    assert result.success
    assert result.index_lock_removed
    assert commit_attempts == 4
    assert not lock.exists()

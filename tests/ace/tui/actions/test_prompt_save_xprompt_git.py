"""Git commit and push behavior for saved xprompts and snippets."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git import (
    submit_post_write_action_sequence,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt import (
    _run_git_commit_push_sync,
)
from sase.ace.tui.modals.post_write_actions_modal import PostWriteActionsModal
from sase.ops.names import GIT_POST_WRITE
from sase.post_write_operations import run_post_write_command_sync
from sase.xprompt.write_targets import PostWriteActionKind, PostWriteActionOffer

from ._prompt_save_xprompt_helpers import _CommitHarness


def test_commit_push_confirmation_submits_tracked_task(tmp_path: Path) -> None:
    path = tmp_path / "xprompts" / "review.md"
    path.parent.mkdir()
    path.write_text("body", encoding="utf-8")
    harness = _CommitHarness()
    with (
        patch(
            "sase.xprompt.write_targets.get_git_root",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.xprompt.write_targets.has_git_changes",
            return_value=True,
        ),
    ):
        harness._offer_git_commit(str(path), is_new=True, xprompt_name="review")
        modal, callback = harness.pushed[0]
        assert isinstance(modal, PostWriteActionsModal)
        assert callable(callback)
        callback((PostWriteActionKind.COMMIT_PUSH,))
    assert len(harness.submitted) == 1
    args, kwargs = harness.submitted[0]
    assert args == (
        [
            "sase",
            "stitch",
            "post-write",
            "commit-push",
            "xprompts/review.md",
            "--json",
        ],
    )
    assert kwargs["operation"] == GIT_POST_WRITE
    assert kwargs["concurrency_keys"] == (
        f"xprompt-commit:{tmp_path}:xprompts/review.md",
    )
    request = kwargs["request"]
    assert isinstance(request, dict)
    assert request["file_path"] == str(path)
    assert request["git_root"] == str(tmp_path)


def test_successful_snippet_commit_refreshes_config_catalog(tmp_path: Path) -> None:
    path = tmp_path / "sase.yml"
    path.write_text("ace: {}\n", encoding="utf-8")
    harness = _CommitHarness()
    with (
        patch(
            "sase.xprompt.write_targets.get_git_root",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.xprompt.write_targets.has_git_changes",
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
        _modal, callback = harness.pushed[0]
        assert callable(callback)
        callback((PostWriteActionKind.COMMIT_PUSH,))

    on_complete = harness.submitted[0][1]["on_complete"]
    assert callable(on_complete)
    on_complete(
        SimpleNamespace(
            success=True,
            message="Committed and pushed to remote",
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
            "sase.xprompt.write_targets.get_git_root",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.xprompt.write_targets.has_git_changes",
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
        _modal, callback = harness.pushed[0]
        assert callable(callback)
        callback(())
        assert harness.submitted == []

        callback((PostWriteActionKind.COMMIT_PUSH,))

    on_complete = harness.submitted[0][1]["on_complete"]
    assert callable(on_complete)
    on_complete(
        SimpleNamespace(success=False, message="chezmoi apply failed", payload=False)
    )

    assert harness.config_refreshes == []


def test_git_commit_push_worker_runs_git_sequence(tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, _kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    path = tmp_path / "review.md"
    with (
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
            side_effect=run,
        ),
        patch("sase.config.apply_chezmoi") as apply_chezmoi,
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert result.success is True
    apply_chezmoi.assert_not_called()
    assert [argv for argv, _kwargs in calls[-3:]] == [
        ["git", "-C", str(tmp_path), "commit", "-m", "chore: Add xprompt review"],
        ["git", "-C", str(tmp_path), "pull", "--rebase"],
        ["git", "-C", str(tmp_path), "push"],
    ]
    assert all(kwargs["stdin"] is subprocess.DEVNULL for _argv, kwargs in calls)
    assert all(kwargs["start_new_session"] is True for _argv, kwargs in calls)
    assert all(
        isinstance(kwargs["env"], dict) and kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        for _argv, kwargs in calls
    )


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


def test_post_write_sequence_waits_for_success_before_next_task() -> None:
    harness = _CommitHarness()
    offers = (
        PostWriteActionOffer(
            kind=PostWriteActionKind.COMMIT_PUSH,
            key="c",
            label="Commit & push",
            subtitle="Commit.",
            default_on=True,
            file_path="/repo/review.md",
            rel_path="review.md",
            git_root="/repo",
            commit_message="chore: update xprompt review",
        ),
        PostWriteActionOffer(
            kind=PostWriteActionKind.APPLY_CHEZMOI,
            key="a",
            label="Apply chezmoi",
            subtitle="Apply.",
            default_on=True,
            file_path="/repo/review.md",
            rel_path="review.md",
            apply_target="/home/u/sase/xprompts/review.md",
        ),
    )

    submit_post_write_action_sequence(harness, harness, offers)

    assert len(harness.submitted) == 1
    on_complete = harness.submitted[0][1]["on_complete"]
    assert callable(on_complete)
    on_complete(SimpleNamespace(success=True, message="committed", payload=False))

    assert len(harness.submitted) == 2
    assert harness.submitted[1][0][0] == [
        "sase",
        "stitch",
        "post-write",
        "chezmoi-apply",
        "review.md",
        "--json",
    ]


def test_post_write_sequence_stops_after_failed_task() -> None:
    harness = _CommitHarness()
    offers = (
        PostWriteActionOffer(
            kind=PostWriteActionKind.COMMIT_PUSH,
            key="c",
            label="Commit & push",
            subtitle="Commit.",
            default_on=True,
            file_path="/repo/review.md",
            rel_path="review.md",
            git_root="/repo",
            commit_message="chore: update xprompt review",
        ),
        PostWriteActionOffer(
            kind=PostWriteActionKind.APPLY_CHEZMOI,
            key="a",
            label="Apply chezmoi",
            subtitle="Apply.",
            default_on=True,
            file_path="/repo/review.md",
            rel_path="review.md",
            apply_target="/home/u/sase/xprompts/review.md",
        ),
    )

    submit_post_write_action_sequence(harness, harness, offers)

    assert len(harness.submitted) == 1
    on_complete = harness.submitted[0][1]["on_complete"]
    assert callable(on_complete)
    on_complete(SimpleNamespace(success=False, message="failed", payload=False))

    assert len(harness.submitted) == 1


def test_generic_post_write_action_uses_noninteractive_runner_with_cwd() -> None:
    offer = PostWriteActionOffer(
        kind=PostWriteActionKind.MEMORY_INIT,
        key="m",
        label="sase memory init",
        subtitle="Run.",
        default_on=True,
        file_path="/repo/sase/memory/foo.md",
        rel_path="sase/memory/foo.md",
        cwd="/repo",
        command=("sase", "memory", "init"),
    )
    completed = subprocess.CompletedProcess(
        list(offer.command),
        0,
        stdout="ok",
        stderr="",
    )

    with patch(
        "sase.post_write_operations.run_noninteractive",
        return_value=completed,
    ) as run_noninteractive:
        result = run_post_write_command_sync(offer.command, cwd=offer.cwd)

    assert result.success is True
    run_noninteractive.assert_called_once_with(offer.command, cwd="/repo")


def test_timed_out_post_write_action_returns_failed_task_result() -> None:
    offer = PostWriteActionOffer(
        kind=PostWriteActionKind.MEMORY_INIT,
        key="m",
        label="sase memory init",
        subtitle="Run.",
        default_on=True,
        file_path="/repo/sase/memory/foo.md",
        rel_path="sase/memory/foo.md",
        cwd="/repo",
        command=("sase", "memory", "init"),
    )

    with patch(
        "sase.post_write_operations.run_noninteractive",
        side_effect=subprocess.TimeoutExpired(list(offer.command), 0.5),
    ):
        result = run_post_write_command_sync(offer.command, cwd=offer.cwd)

    assert result.success is False
    assert result.message == "sase memory init timed out after 0.5s"

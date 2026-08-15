"""Noninteractive post-write commit and apply operations."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

from sase.git_lock_retry import run_with_git_lock_retry
from sase.noninteractive_subprocess import run_noninteractive
from sase.workspace_provider.utils import non_interactive_git_env


@dataclass(frozen=True)
class GitCommitPushResult:
    """Result from the synchronous git commit/push helper."""

    success: bool
    message: str
    index_lock_removed: bool = False


def run_git_commit_push_sync(
    *,
    git_root: str,
    file_path: str,
    commit_message: str,
) -> GitCommitPushResult:
    """Synchronously stage, commit, pull, and push one file."""
    index_lock_removed = False

    def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal index_lock_removed
        argv = ["git", "-C", git_root, *args]
        result, outcome = run_with_git_lock_retry(
            lambda: subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                start_new_session=True,
                env=non_interactive_git_env(),
            ),
            cwd=git_root,
        )
        index_lock_removed = index_lock_removed or outcome.lock_removed
        return result

    add_result = _run_git(["add", "--", file_path])
    if add_result.returncode != 0:
        return GitCommitPushResult(
            False,
            f"Git add failed: {process_error_text(add_result)}",
            index_lock_removed,
        )

    commit_result = _run_git(["commit", "-m", commit_message])
    if commit_result.returncode != 0:
        return GitCommitPushResult(
            False,
            f"Commit failed: {process_error_text(commit_result)}",
            index_lock_removed,
        )

    pull_result = _run_git(["pull", "--rebase"])
    if pull_result.returncode != 0:
        return GitCommitPushResult(
            False,
            f"Pull failed: {process_error_text(pull_result)}",
            index_lock_removed,
        )

    push_result = _run_git(["push"])
    if push_result.returncode != 0:
        return GitCommitPushResult(
            False,
            f"Push failed: {process_error_text(push_result)}",
            index_lock_removed,
        )

    return GitCommitPushResult(
        True,
        "Committed and pushed to remote",
        index_lock_removed,
    )


def run_chezmoi_apply_sync(target: str) -> GitCommitPushResult:
    """Run chezmoi apply for a previously written source target."""
    from sase.config import apply_chezmoi

    try:
        result = apply_chezmoi(target)
    except FileNotFoundError:
        return GitCommitPushResult(False, "chezmoi not found on PATH")
    if result.returncode != 0:
        return GitCommitPushResult(
            False,
            f"chezmoi apply failed: {process_error_text(result)}",
        )
    return GitCommitPushResult(True, f"Applied chezmoi changes to {target}")


def run_post_write_command_sync(
    command: Sequence[str],
    *,
    cwd: str | None,
) -> GitCommitPushResult:
    """Run a noninteractive post-write command."""
    label = " ".join(command)
    try:
        result = run_noninteractive(command, cwd=cwd)
    except FileNotFoundError:
        return GitCommitPushResult(False, f"{command[0]} not found on PATH")
    except subprocess.TimeoutExpired as exc:
        timeout = "unknown" if exc.timeout is None else f"{exc.timeout:g}"
        return GitCommitPushResult(False, f"{label} timed out after {timeout}s")
    if result.returncode != 0:
        return GitCommitPushResult(
            False,
            f"{label} failed: {process_error_text(result)}",
        )
    return GitCommitPushResult(True, f"Ran {label}")


def process_error_text(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "command failed").strip()


__all__ = [
    "GitCommitPushResult",
    "process_error_text",
    "run_chezmoi_apply_sync",
    "run_git_commit_push_sync",
    "run_post_write_command_sync",
]

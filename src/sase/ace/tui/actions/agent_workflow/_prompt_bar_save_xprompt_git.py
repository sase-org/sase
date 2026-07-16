"""Git commit/push helpers for prompt-bar xprompt saves."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass

from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitCommitPushResult:
    """Result from the synchronous git commit/push helper."""

    success: bool
    message: str
    index_lock_removed: bool = False


class PromptBarSaveXpromptGitMixin:
    """Offer and run commit/push tasks after saving prompts or snippets."""

    def _offer_git_commit(
        self,
        file_path: str,
        *,
        is_new: bool,
        xprompt_name: str,
        noun: str = "xprompt",
        commit_type: str = "xprompt",
    ) -> None:
        """If the file is in a git repo and has changes, offer to commit/push."""
        from ...modals import ConfirmActionModal
        from ...modals.xprompt_browser_helpers import get_git_root, has_git_changes

        git_root = get_git_root(file_path)
        if git_root is None or not has_git_changes(git_root, file_path):
            return

        rel_path = os.path.relpath(file_path, git_root)
        verb = "Add" if is_new else "Update"
        subject = f"chore: {verb} {noun} {xprompt_name}"
        from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

        message = apply_auto_commit_type_tag(subject, commit_type)

        def _on_commit_push_answer(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._submit_xprompt_commit_task(
                git_root=git_root,
                file_path=file_path,
                rel_path=rel_path,
                message=message,
                noun=noun,
            )

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Commit & Push",
                "Commit and push your saved changes?",
                subject=rel_path,
                icon="↑",
                confirm_label="Commit & push",
                cancel_label="Skip",
                default="confirm",
            ),
            _on_commit_push_answer,
        )

    def _submit_xprompt_commit_task(
        self,
        *,
        git_root: str,
        file_path: str,
        rel_path: str,
        message: str,
        noun: str = "xprompt",
    ) -> None:
        """Run the git commit/push flow through the tracked task queue."""

        def _task() -> TrackedTaskResult[bool]:
            result = run_git_commit_push_sync(
                git_root=git_root,
                file_path=file_path,
                commit_message=message,
            )
            return TrackedTaskResult(
                success=result.success,
                message=result.message,
                payload=result.index_lock_removed,
                error=None if result.success else result.message,
            )

        def _on_complete(completion: TrackedTaskCompletion[bool]) -> None:
            if completion.success:
                self.notify(completion.message)  # type: ignore[attr-defined]
            else:
                self.notify(  # type: ignore[attr-defined]
                    completion.message,
                    severity="error",
                )
            if completion.payload:
                self.notify(  # type: ignore[attr-defined]
                    git_index_lock_retry_message(git_root),
                    severity="warning",
                )

        submit = getattr(self, "_submit_tracked_task", None)
        if submit is None:
            self.notify(  # type: ignore[attr-defined]
                f"Could not commit {noun}: background task queue unavailable.",
                severity="error",
            )
            return

        submit(
            f"{noun}-commit",
            rel_path,
            git_root,
            _task,
            display_name=f"commit {noun} {rel_path}",
            dedup_key=f"{noun}-commit:{git_root}:{rel_path}",
            duplicate_message=f"Another {noun} commit is already running for {rel_path}.",
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )


def run_git_commit_push_sync(
    *,
    git_root: str,
    file_path: str,
    commit_message: str,
) -> GitCommitPushResult:
    """Synchronously stage, commit, pull, push, and optionally apply chezmoi."""
    index_lock_removed = False

    def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal index_lock_removed
        argv = ["git", "-C", git_root, *args]
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result
        combined_output = "\n".join(
            part for part in (result.stderr, result.stdout) if part
        )
        if not _is_index_lock_error(combined_output):
            return result
        if not _remove_git_index_lock(git_root):
            return result
        index_lock_removed = True
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
        )

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

    from sase.config import apply_chezmoi, get_use_chezmoi

    if not get_use_chezmoi():
        return GitCommitPushResult(
            True,
            "Committed and pushed to remote",
            index_lock_removed,
        )

    try:
        chezmoi_result = apply_chezmoi()
    except FileNotFoundError:
        return GitCommitPushResult(
            False,
            "chezmoi not found on PATH",
            index_lock_removed,
        )
    if chezmoi_result.returncode != 0:
        return GitCommitPushResult(
            False,
            f"chezmoi apply failed: {process_error_text(chezmoi_result)}",
            index_lock_removed,
        )
    return GitCommitPushResult(
        True,
        "Committed and pushed to remote; applied chezmoi changes",
        index_lock_removed,
    )


def _is_index_lock_error(text: str) -> bool:
    """Return True when git output names an existing index lock."""
    return "index.lock" in text


def _remove_git_index_lock(git_root: str) -> bool:
    from sase.axe.runner_workspace import git_index_lock_path

    lock_path = git_index_lock_path(git_root)
    if lock_path is None:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning("Failed to remove git index lock %s", lock_path, exc_info=True)
        return False
    logger.warning("Removed git index lock before retrying commit: %s", lock_path)
    return True


def git_index_lock_retry_message(git_root: str) -> str:
    repo_name = os.path.basename(os.path.normpath(git_root)) or git_root
    return f"Removed a stale git index.lock in {repo_name} and retried the commit."


def process_error_text(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "command failed").strip()


__all__ = [
    "GitCommitPushResult",
    "PromptBarSaveXpromptGitMixin",
    "git_index_lock_retry_message",
    "run_git_commit_push_sync",
]

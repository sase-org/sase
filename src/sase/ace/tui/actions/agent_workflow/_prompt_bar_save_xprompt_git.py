"""Git commit/push helpers for prompt-bar xprompt saves."""

from __future__ import annotations

import os
import subprocess

from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)


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

        def _task() -> TrackedTaskResult[None]:
            success, result_message = run_git_commit_push_sync(
                git_root=git_root,
                file_path=file_path,
                commit_message=message,
            )
            return TrackedTaskResult(
                success=success,
                message=result_message,
                error=None if success else result_message,
            )

        def _on_complete(completion: TrackedTaskCompletion[None]) -> None:
            if completion.success:
                self.notify(completion.message)  # type: ignore[attr-defined]
            else:
                self.notify(  # type: ignore[attr-defined]
                    completion.message,
                    severity="error",
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
) -> tuple[bool, str]:
    """Synchronously stage, commit, pull, push, and optionally apply chezmoi."""
    add_result = subprocess.run(
        ["git", "-C", git_root, "add", "--", file_path],
        capture_output=True,
        text=True,
        check=False,
    )
    if add_result.returncode != 0:
        return False, f"Git add failed: {process_error_text(add_result)}"

    commit_result = subprocess.run(
        ["git", "-C", git_root, "commit", "-m", commit_message],
        capture_output=True,
        text=True,
        check=False,
    )
    if commit_result.returncode != 0:
        return False, f"Commit failed: {process_error_text(commit_result)}"

    pull_result = subprocess.run(
        ["git", "-C", git_root, "pull", "--rebase"],
        capture_output=True,
        text=True,
        check=False,
    )
    if pull_result.returncode != 0:
        return False, f"Pull failed: {process_error_text(pull_result)}"

    push_result = subprocess.run(
        ["git", "-C", git_root, "push"],
        capture_output=True,
        text=True,
        check=False,
    )
    if push_result.returncode != 0:
        return False, f"Push failed: {process_error_text(push_result)}"

    from sase.config import get_use_chezmoi

    if not get_use_chezmoi():
        return True, "Committed and pushed to remote"

    try:
        chezmoi_result = subprocess.run(
            ["chezmoi", "apply"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "chezmoi not found on PATH"
    if chezmoi_result.returncode != 0:
        return False, f"chezmoi apply failed: {process_error_text(chezmoi_result)}"
    return True, "Committed and pushed to remote; applied chezmoi changes"


def process_error_text(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "command failed").strip()


__all__ = ["PromptBarSaveXpromptGitMixin", "run_git_commit_push_sync"]

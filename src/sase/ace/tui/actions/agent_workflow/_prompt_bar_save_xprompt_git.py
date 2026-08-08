"""Git commit/push helpers for prompt-bar xprompt saves."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.git_lock_retry import run_with_git_lock_retry
from sase.xprompt.write_targets import (
    PostWriteActionKind,
    PostWriteActionOffer,
    WrittenFileKind,
    XPromptWriteTarget,
    build_post_write_action_offers,
    classify_written_file,
    write_target_for_written_path,
)


@dataclass(frozen=True)
class GitCommitPushResult:
    """Result from the synchronous git commit/push helper."""

    success: bool
    message: str
    index_lock_removed: bool = False


class PromptBarSaveXpromptGitMixin:
    """Offer and run commit/push tasks after saving prompts or snippets."""

    async def _offer_post_write_actions(
        self,
        target: XPromptWriteTarget,
        *,
        kind: WrittenFileKind,
        is_new: bool,
        xprompt_name: str,
        noun: str = "xprompt",
        commit_type: str = "xprompt",
        refresh_config_on_success: bool = False,
    ) -> None:
        """Build and push the post-write action chooser off the event loop."""
        import asyncio

        offers = await asyncio.to_thread(
            build_post_write_action_offers,
            target,
            kind=kind,
            is_new=is_new,
            xprompt_name=xprompt_name,
            noun=noun,
            commit_type=commit_type,
        )
        self._push_post_write_actions(
            offers,
            target=target,
            noun=noun,
            refresh_config_on_success=refresh_config_on_success,
        )

    def _offer_git_commit(
        self,
        file_path: str,
        *,
        is_new: bool,
        xprompt_name: str,
        noun: str = "xprompt",
        commit_type: str = "xprompt",
    ) -> None:
        """Compatibility wrapper for older save callers."""
        target = write_target_for_written_path(file_path)
        kind = classify_written_file(target.write_path, read_path=target.read_path)
        offers = build_post_write_action_offers(
            target,
            kind=kind,
            is_new=is_new,
            xprompt_name=xprompt_name,
            noun=noun,
            commit_type=commit_type,
        )
        self._push_post_write_actions(
            offers,
            target=target,
            noun=noun,
            refresh_config_on_success=noun == "snippet",
        )

    def _push_post_write_actions(
        self,
        offers: tuple[PostWriteActionOffer, ...],
        *,
        target: XPromptWriteTarget,
        noun: str,
        refresh_config_on_success: bool = False,
    ) -> None:
        """Push the post-write chooser for already-built offers."""
        if not offers:
            return
        from ...modals.post_write_actions_modal import PostWriteActionsModal

        by_kind = {offer.kind: offer for offer in offers}

        def _on_actions_selected(
            selected: tuple[PostWriteActionKind, ...] | None,
        ) -> None:
            if not selected:
                return
            selected_offers = tuple(
                by_kind[kind] for kind in selected if kind in by_kind
            )
            submit_post_write_action_sequence(
                self,
                self,
                selected_offers,
                noun=noun,
                refresh_config_on_success=refresh_config_on_success,
            )

        self.push_screen(  # type: ignore[attr-defined]
            PostWriteActionsModal(offers, subject=_post_write_subject(target, offers)),
            _on_actions_selected,
        )

    def _submit_xprompt_commit_task(
        self,
        *,
        git_root: str,
        file_path: str,
        rel_path: str,
        message: str,
        noun: str = "xprompt",
        refresh_config_on_success: bool = False,
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
                if refresh_config_on_success:
                    refresh_config = getattr(
                        self,
                        "_request_prompt_catalog_config_refresh",
                        None,
                    )
                    if callable(refresh_config):
                        refresh_config(reason="snippet_commit_apply")
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
    """Synchronously stage, commit, pull, and push one file."""
    index_lock_removed = False

    def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal index_lock_removed
        argv = ["git", "-C", git_root, *args]
        result, outcome = run_with_git_lock_retry(
            lambda: subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=False,
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


def submit_post_write_action_sequence(
    notifier: Any,
    submit_owner: Any,
    offers: tuple[PostWriteActionOffer, ...],
    *,
    noun: str = "xprompt",
    refresh_config_on_success: bool = False,
) -> None:
    """Submit selected post-write actions as ordered tracked tasks."""
    pending = list(offers)

    def _finish_sequence() -> None:
        if not refresh_config_on_success:
            return
        refresh_config = getattr(
            notifier,
            "_request_prompt_catalog_config_refresh",
            None,
        )
        if callable(refresh_config):
            refresh_config(reason="snippet_commit_apply")

    def _submit_next() -> None:
        if not pending:
            _finish_sequence()
            return
        offer = pending.pop(0)
        _submit_post_write_action(
            notifier,
            submit_owner,
            offer,
            noun=noun,
            on_success=_submit_next,
        )

    _submit_next()


def _submit_post_write_action(
    notifier: Any,
    submit_owner: Any,
    offer: PostWriteActionOffer,
    *,
    noun: str,
    on_success: Callable[[], None],
) -> None:
    submit = getattr(submit_owner, "_submit_tracked_task", None)
    if not callable(submit):
        notifier.notify(
            f"Could not run {offer.label}: background task queue unavailable.",
            severity="error",
        )
        return

    def _task() -> TrackedTaskResult[bool]:
        result = _run_post_write_action_sync(offer)
        return TrackedTaskResult(
            success=result.success,
            message=result.message,
            payload=result.index_lock_removed,
            error=None if result.success else result.message,
        )

    def _on_complete(completion: TrackedTaskCompletion[bool]) -> None:
        notifier.notify(
            completion.message,
            severity="information" if completion.success else "error",
        )
        if completion.payload and offer.git_root:
            notifier.notify(
                git_index_lock_retry_message(offer.git_root),
                severity="warning",
            )
        if completion.success:
            on_success()

    metadata = _post_write_task_metadata(offer, noun=noun)
    submit(
        metadata["task_type"],
        metadata["cl_name"],
        metadata["project_file"],
        _task,
        display_name=metadata["display_name"],
        dedup_key=metadata["dedup_key"],
        duplicate_message=metadata["duplicate_message"],
        on_complete=_on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )


def _run_post_write_action_sync(offer: PostWriteActionOffer) -> GitCommitPushResult:
    if offer.kind is PostWriteActionKind.COMMIT_PUSH:
        if offer.git_root is None or offer.commit_message is None:
            return GitCommitPushResult(False, "Commit action is missing git metadata")
        return run_git_commit_push_sync(
            git_root=offer.git_root,
            file_path=offer.file_path,
            commit_message=offer.commit_message,
        )

    if offer.kind is PostWriteActionKind.APPLY_CHEZMOI:
        if offer.apply_target is None:
            return GitCommitPushResult(False, "chezmoi apply target is missing")
        from sase.config import apply_chezmoi

        try:
            result = apply_chezmoi(offer.apply_target)
        except FileNotFoundError:
            return GitCommitPushResult(False, "chezmoi not found on PATH")
        if result.returncode != 0:
            return GitCommitPushResult(
                False,
                f"chezmoi apply failed: {process_error_text(result)}",
            )
        return GitCommitPushResult(
            True,
            f"Applied chezmoi changes to {offer.apply_target}",
        )

    if offer.command:
        try:
            result = subprocess.run(
                list(offer.command),
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return GitCommitPushResult(False, f"{offer.command[0]} not found on PATH")
        label = " ".join(offer.command)
        if result.returncode != 0:
            return GitCommitPushResult(
                False,
                f"{label} failed: {process_error_text(result)}",
            )
        return GitCommitPushResult(True, f"Ran {label}")

    return GitCommitPushResult(False, f"Unsupported post-write action: {offer.kind}")


def _post_write_task_metadata(
    offer: PostWriteActionOffer,
    *,
    noun: str,
) -> dict[str, str]:
    if offer.kind is PostWriteActionKind.COMMIT_PUSH:
        git_root = offer.git_root or ""
        return {
            "task_type": f"{noun}-commit",
            "cl_name": offer.rel_path,
            "project_file": git_root,
            "display_name": f"commit {noun} {offer.rel_path}",
            "dedup_key": f"{noun}-commit:{git_root}:{offer.rel_path}",
            "duplicate_message": (
                f"Another {noun} commit is already running for {offer.rel_path}."
            ),
        }
    if offer.kind is PostWriteActionKind.APPLY_CHEZMOI:
        target = offer.apply_target or offer.file_path
        return {
            "task_type": f"{noun}-chezmoi-apply",
            "cl_name": offer.rel_path,
            "project_file": target,
            "display_name": f"apply chezmoi {target}",
            "dedup_key": f"{noun}-chezmoi-apply:{target}",
            "duplicate_message": f"Another chezmoi apply is already running for {target}.",
        }
    if offer.kind is PostWriteActionKind.MEMORY_INIT:
        return {
            "task_type": "xprompt-memory-init",
            "cl_name": offer.rel_path,
            "project_file": offer.file_path,
            "display_name": "run sase memory init",
            "dedup_key": "xprompt-memory-init",
            "duplicate_message": "Another sase memory init is already running.",
        }
    return {
        "task_type": "xprompt-skill-init",
        "cl_name": offer.rel_path,
        "project_file": offer.file_path,
        "display_name": "run sase skill init",
        "dedup_key": "xprompt-skill-init",
        "duplicate_message": "Another sase skill init is already running.",
    }


def _post_write_subject(
    target: XPromptWriteTarget,
    offers: tuple[PostWriteActionOffer, ...],
) -> str:
    rel_path = offers[0].rel_path if offers else str(target.write_path)
    if target.via_chezmoi and target.apply_target is not None:
        return f"{rel_path}\nchezmoi source for {target.apply_target}"
    return rel_path


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
    "submit_post_write_action_sequence",
]

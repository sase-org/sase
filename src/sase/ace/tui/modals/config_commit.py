"""Shared post-write commit workflow for Config TUI surfaces.

Config editors hand this module the path that was actually written.  That is
important for chezmoi-backed edits: the written source belongs to the chezmoi
repository, while the applied home target generally does not.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigCommitOffer:
    """A ready-to-confirm commit and push for one written config file."""

    git_root: str
    file_path: str
    rel_path: str
    message: str


def build_config_commit_offer(
    target_path: str,
    *,
    subject: str,
) -> ConfigCommitOffer | None:
    """Build a config commit offer when *target_path* is dirty in git.

    Repository discovery and status inspection run subprocesses, so callers
    must invoke this helper off Textual's event loop.
    """
    from sase.ace.tui.modals.xprompt_browser_helpers import (
        get_git_root,
        has_git_changes,
    )
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    try:
        git_root = get_git_root(target_path)
        if git_root is None or not has_git_changes(git_root, target_path):
            return None
        rel_path = os.path.relpath(target_path, git_root)
    except (OSError, ValueError):
        return None
    return ConfigCommitOffer(
        git_root=git_root,
        file_path=target_path,
        rel_path=rel_path,
        message=apply_auto_commit_type_tag(subject, "config"),
    )


def push_config_commit_prompt(
    app: Any,
    offer: ConfigCommitOffer,
    *,
    message: str,
    on_confirm: Callable[[ConfigCommitOffer], None],
) -> None:
    """Push the canonical y/n commit prompt for *offer*."""
    from .confirm_action_modal import ConfirmActionModal

    def _on_answer(confirmed: bool | None) -> None:
        if confirmed:
            on_confirm(offer)

    app.push_screen(
        ConfirmActionModal(
            "Commit & Push",
            message,
            subject=offer.rel_path,
            icon="↑",
            confirm_label="Commit & push",
            cancel_label="Skip",
            default="confirm",
        ),
        _on_answer,
    )


def submit_config_commit_task(
    app: Any,
    offer: ConfigCommitOffer,
    *,
    display_name: str,
) -> None:
    """Submit the established config commit/pull/push tracked task."""
    from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git import (
        GitCommitPushResult,
        git_index_lock_retry_message,
        run_git_commit_push_sync,
    )
    from sase.ace.tui.actions.task_actions import (
        TrackedTaskCompletion,
        TrackedTaskResult,
    )

    def _task() -> TrackedTaskResult[bool]:
        result: GitCommitPushResult = run_git_commit_push_sync(
            git_root=offer.git_root,
            file_path=offer.file_path,
            commit_message=offer.message,
        )
        return TrackedTaskResult(
            success=result.success,
            message=result.message,
            payload=result.index_lock_removed,
            error=None if result.success else result.message,
        )

    def _on_complete(completion: TrackedTaskCompletion[bool]) -> None:
        app.notify(
            completion.message,
            severity="information" if completion.success else "error",
        )
        if completion.payload:
            app.notify(
                git_index_lock_retry_message(offer.git_root),
                severity="warning",
            )

    submit = getattr(app, "_submit_tracked_task", None)
    if submit is None:
        app.notify(
            "Could not commit: background task queue unavailable.",
            severity="error",
        )
        return
    submit(
        "config-commit",
        offer.rel_path,
        offer.git_root,
        _task,
        display_name=display_name,
        dedup_key=f"config-commit:{offer.git_root}:{offer.rel_path}",
        duplicate_message=(
            f"Another config commit is already running for {offer.rel_path}."
        ),
        on_complete=_on_complete,
        reload_on_complete=False,
        notify_on_complete=False,
    )


__all__ = [
    "ConfigCommitOffer",
    "build_config_commit_offer",
    "push_config_commit_prompt",
    "submit_config_commit_task",
]

"""Git mutation helpers for Agents-tab commit reverts."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence

from sase.ace import revert_agent_git as _git
from sase.ace.revert_agent_git import commit_subject, current_head, worktree_is_clean
from sase.ace.revert_agent_marker import PushOutcome
from sase.git_lock_retry import run_with_git_lock_retry


def apply_revert_transaction(
    workspace_dir: str,
    ordered_shas: tuple[str, ...],
    message: str,
) -> tuple[bool, str | None]:
    """Revert *ordered_shas* (newest-first) as one commit, atomically.

    Captures ``HEAD`` first, applies ``git revert --no-commit`` for every SHA,
    then creates a single commit. On any failure the worktree is rolled back to
    the captured ``HEAD`` via :func:`_rollback_to`. Returns ``(success,
    error_detail)``; ``error_detail`` is ``None`` on success.
    """
    head_before = current_head(workspace_dir)

    revert = _run_git(
        workspace_dir, ["revert", "--no-commit", "--no-edit", *ordered_shas]
    )
    if revert.returncode != 0:
        detail = (revert.stderr or revert.stdout or "git revert failed").strip()
        rollback_to(workspace_dir, head_before)
        return False, detail

    commit = _run_git(workspace_dir, ["commit", "--no-verify", "-m", message])
    if commit.returncode != 0:
        detail = (commit.stderr or commit.stdout or "git commit failed").strip()
        rollback_to(workspace_dir, head_before)
        return False, detail

    return True, None


def rollback_to(workspace_dir: str, head_before: str | None) -> None:
    """Best-effort restore the worktree to its pre-operation state.

    Aborts any in-progress revert sequence first, then if the worktree was
    dirtied or ``HEAD`` advanced past the captured commit, force-resets back to
    it. Because callers require a clean-worktree precondition, the hard reset
    only discards changes introduced by the failed revert attempt.
    """
    _run_git(workspace_dir, ["revert", "--abort"])
    if head_before is None:
        return
    head_now = current_head(workspace_dir)
    clean = worktree_is_clean(workspace_dir)
    if head_now != head_before or clean is not True:
        _run_git(workspace_dir, ["reset", "--hard", head_before])


def build_revert_message(
    workspace_dir: str,
    agent_name: str,
    shas: tuple[str, ...],
) -> str:
    lines = [
        f"Revert {len(shas)} commit(s) from agent '{agent_name}'",
        "",
        "This reverts the following commits:",
    ]
    for sha in shas:
        subject = commit_subject(workspace_dir, sha)
        lines.append(f"- {sha[:9]} {subject}".rstrip())
    return "\n".join(lines)


def build_bulk_revert_message(
    workspace_dir: str,
    agent_names: Sequence[str],
    shas: tuple[str, ...],
) -> str:
    names = ", ".join(agent_names)
    lines = [
        f"Revert {len(shas)} commit(s) from {len(agent_names)} agent(s)",
        "",
        f"Agents: {names}",
        "",
        "This reverts the following commits:",
    ]
    for sha in shas:
        subject = commit_subject(workspace_dir, sha)
        lines.append(f"- {sha[:9]} {subject}".rstrip())
    return "\n".join(lines)


def push_revert_commit(workspace_dir: str) -> PushOutcome:
    """Push the current branch to ``origin`` when both are available.

    Skips (``attempted=False``) when there is no ``origin`` remote or no
    current branch. Otherwise runs ``git push origin <branch>`` and reports
    success or the push failure detail so callers can surface it.
    """
    remote = _run_git(workspace_dir, ["remote", "get-url", "origin"])
    if remote.returncode != 0 or not remote.stdout.strip():
        return PushOutcome(
            attempted=False, pushed=False, skipped_reason="no origin remote"
        )
    branch = _run_git(workspace_dir, ["symbolic-ref", "--short", "HEAD"])
    branch_name = branch.stdout.strip()
    if branch.returncode != 0 or not branch_name:
        return PushOutcome(
            attempted=False,
            pushed=False,
            skipped_reason="detached HEAD or no current branch",
        )
    push = _run_git(workspace_dir, ["push", "origin", branch_name])
    if push.returncode == 0:
        return PushOutcome(attempted=True, pushed=True)
    detail = (push.stderr or push.stdout or "git push failed").strip()
    return PushOutcome(attempted=True, pushed=False, error=detail)


def run_git_for_revert(
    workspace_dir: str,
    args: list[str],
    *,
    timeout: int = _git._GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run git, honoring legacy monkeypatches on ``sase.ace.revert_agent``."""
    facade = sys.modules.get("sase.ace.revert_agent")
    facade_runner = getattr(facade, "_run_git", None)
    if (
        callable(facade_runner)
        and facade_runner is not _git.run_git
        and facade_runner is not run_git_for_revert
    ):
        result, _outcome = run_with_git_lock_retry(
            lambda: facade_runner(workspace_dir, args, timeout=timeout),
            cwd=workspace_dir,
        )
        return result
    return _git.run_git(workspace_dir, args, timeout=timeout)


_apply_revert_transaction = apply_revert_transaction
_rollback_to = rollback_to
_build_revert_message = build_revert_message
_build_bulk_revert_message = build_bulk_revert_message
_push_revert_commit = push_revert_commit
_run_git = run_git_for_revert


__all__ = [
    "apply_revert_transaction",
    "build_bulk_revert_message",
    "build_revert_message",
    "push_revert_commit",
    "rollback_to",
    "run_git_for_revert",
]

"""Backend for reverting commits associated with done agents.

Powers the Agents-tab leader ``,r`` action. Commits are associated with an
agent by the exact ``AGENT=<name>`` provenance tag written into commit messages
(see :mod:`sase.workflows.commit.runtime_tags`). This is git-only: non-git
workspaces fail with an explicit unsupported message rather than reusing
ChangeSpec prune/abandon semantics.

The flow is two-phase so the TUI can confirm before mutating anything:

1. :func:`preview_agent_revert` discovers candidate commits newest-first and
   validates the worktree.
2. :func:`execute_agent_revert` re-validates, applies ``git revert --no-commit``
   for the previewed SHAs, creates a single revert commit, and pushes when an
   ``origin`` remote and branch are available.

A parallel *bulk* path (:func:`preview_agents_revert` /
:func:`execute_agents_revert`) reverts the combined commit set of several
marked agents as a single atomic git transaction.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.ace.revert_agent_discovery import (
    discover_agent_commits as _discover_agent_commits,
    discover_bulk_commits as _discover_bulk_commits,
)
from sase.ace.revert_agent_git import (
    commit_exists,
    commit_subject,
    current_head,
    is_git_worktree,
    run_git as _run_git,
    worktree_is_clean,
)
from sase.ace.revert_agent_models import (
    BulkRevertPreview,
    BulkRevertResult,
    RevertCommit,
    RevertPreview,
    RevertResult,
    RevertTarget,
)
from sase.ace.revert_agent_resolution import (
    resolve_revert_agent_name,
    resolve_revert_family_base,
    resolve_revert_workspace_dir,
)


@dataclass(frozen=True)
class _PushOutcome:
    """Result of attempting to push a revert commit to ``origin``.

    Distinguishes three outcomes the old ``bool`` return collapsed: a skipped
    push (no remote/branch, ``attempted=False``), a successful push
    (``pushed=True``), and a failed push to an available remote (``error`` set).
    """

    attempted: bool
    pushed: bool
    skipped_reason: str | None = None
    error: str | None = None


def preview_agent_revert(
    workspace_dir: str | None,
    agent_name: str,
    *,
    family_base: str | None = None,
) -> RevertPreview:
    """Validate the worktree and discover commits to revert."""
    scope = "family" if family_base else "agent"

    def _fail(error: str) -> RevertPreview:
        return RevertPreview(
            agent_name=agent_name,
            scope=scope,
            workspace_dir=workspace_dir or "",
            commits=(),
            error=error,
        )

    if not workspace_dir:
        return _fail("No workspace directory for agent")
    if not is_git_worktree(workspace_dir):
        return _fail("Workspace is not a git worktree (revert is git-only)")

    clean = worktree_is_clean(workspace_dir)
    if clean is None:
        return _fail("Could not read git status for workspace")
    if not clean:
        return _fail("Workspace has uncommitted changes; commit or discard them first")

    commits = _discover_agent_commits(
        workspace_dir, agent_name, family_base=family_base
    )
    if not commits:
        target = f"family '{family_base}'" if family_base else f"agent '{agent_name}'"
        return _fail(f"No commits tagged for {target} were found")

    return RevertPreview(
        agent_name=agent_name,
        scope=scope,
        workspace_dir=workspace_dir,
        commits=tuple(commits),
    )


def execute_agent_revert(
    workspace_dir: str,
    shas: tuple[str, ...] | list[str],
    *,
    agent_name: str,
    artifacts_dir: str | None = None,
) -> RevertResult:
    """Revert *shas* (newest-first) as a single revert commit."""
    ordered = tuple(shas)
    if not ordered:
        return RevertResult(False, "No commits to revert", error="no commits")

    if not is_git_worktree(workspace_dir):
        return RevertResult(
            False,
            "Workspace is not a git worktree (revert is git-only)",
            error="not a git worktree",
        )

    clean = worktree_is_clean(workspace_dir)
    if clean is None:
        return RevertResult(
            False, "Could not read git status for workspace", error="git status failed"
        )
    if not clean:
        return RevertResult(
            False,
            "Workspace has uncommitted changes; aborting revert",
            error="dirty worktree",
        )

    missing = [sha for sha in ordered if not commit_exists(workspace_dir, sha)]
    if missing:
        short = ", ".join(sha[:9] for sha in missing)
        return RevertResult(
            False,
            f"Commit(s) no longer exist: {short}",
            error="missing commits",
        )

    message = _build_revert_message(workspace_dir, agent_name, ordered)
    ok, detail = _apply_revert_transaction(workspace_dir, ordered, message)
    if not ok:
        return RevertResult(
            False,
            f"Revert failed and was rolled back: {detail}",
            error=detail,
        )

    push = _push_revert_commit(workspace_dir)
    if artifacts_dir:
        _write_revert_result(artifacts_dir, agent_name, ordered, push=push)

    if push.error is not None:
        return RevertResult(
            False,
            f"Reverted {len(ordered)} commit(s) for '{agent_name}' locally, "
            f"but push to GitHub failed: {push.error}",
            reverted_shas=ordered,
            pushed=False,
            error=f"git push failed: {push.error}",
        )

    summary = f"Reverted {len(ordered)} commit(s) for '{agent_name}'"
    summary += " and pushed" if push.pushed else ""
    return RevertResult(
        True,
        summary,
        reverted_shas=ordered,
        pushed=push.pushed,
    )


def preview_agents_revert(targets: Sequence[RevertTarget]) -> BulkRevertPreview:
    """Validate the shared worktree and discover the combined commit set.

    All *targets* must share a single workspace; mixed workspaces are rejected
    up front because one ``git revert`` transaction cannot be atomic across
    repositories. Commits are deduplicated by full SHA and ordered newest-first
    across the whole combined set (not per-agent concatenation).
    """
    target_tuple = tuple(targets)
    workspace_dir = target_tuple[0].workspace_dir if target_tuple else ""

    def _fail(error: str) -> BulkRevertPreview:
        return BulkRevertPreview(
            workspace_dir=workspace_dir,
            targets=target_tuple,
            error=error,
        )

    if not target_tuple:
        return _fail("No agents to revert")

    workspaces = {t.workspace_dir for t in target_tuple}
    if len(workspaces) > 1:
        return _fail("Marked agents span multiple workspaces; no changes were applied")

    if not workspace_dir:
        return _fail("No workspace directory for marked agents")
    if not is_git_worktree(workspace_dir):
        return _fail("Workspace is not a git worktree (revert is git-only)")

    clean = worktree_is_clean(workspace_dir)
    if clean is None:
        return _fail("Could not read git status for workspace")
    if not clean:
        return _fail("Workspace has uncommitted changes; commit or discard them first")

    commits, matched = _discover_bulk_commits(workspace_dir, target_tuple)
    if not commits:
        return _fail("No commits tagged for the marked agents were found")

    matched_names = tuple(t.agent_name for t in target_tuple if t.agent_name in matched)
    skipped_names = tuple(
        t.agent_name for t in target_tuple if t.agent_name not in matched
    )

    return BulkRevertPreview(
        workspace_dir=workspace_dir,
        targets=target_tuple,
        commits=tuple(commits),
        matched_target_names=matched_names,
        skipped_target_names=skipped_names,
    )


def execute_agents_revert(preview: BulkRevertPreview) -> BulkRevertResult:
    """Revert a previewed bulk commit set as one atomic git transaction."""
    workspace_dir = preview.workspace_dir
    ordered = tuple(commit.full_sha for commit in preview.commits)
    matched_names = preview.matched_target_names or tuple(
        t.agent_name for t in preview.targets
    )

    if not ordered:
        return BulkRevertResult(False, "No commits to revert", error="no commits")

    if not is_git_worktree(workspace_dir):
        return BulkRevertResult(
            False,
            "Workspace is not a git worktree (revert is git-only)",
            error="not a git worktree",
        )

    clean = worktree_is_clean(workspace_dir)
    if clean is None:
        return BulkRevertResult(
            False, "Could not read git status for workspace", error="git status failed"
        )
    if not clean:
        return BulkRevertResult(
            False,
            "Workspace has uncommitted changes; aborting revert",
            error="dirty worktree",
        )

    missing = [sha for sha in ordered if not commit_exists(workspace_dir, sha)]
    if missing:
        short = ", ".join(sha[:9] for sha in missing)
        return BulkRevertResult(
            False,
            f"Commit(s) no longer exist: {short}",
            error="missing commits",
        )

    message = _build_bulk_revert_message(workspace_dir, matched_names, ordered)
    ok, detail = _apply_revert_transaction(workspace_dir, ordered, message)
    if not ok:
        return BulkRevertResult(
            False,
            f"Bulk revert failed and was rolled back: {detail}",
            error=detail,
        )

    push = _push_revert_commit(workspace_dir)
    matched_set = set(matched_names)
    for target in preview.targets:
        if target.artifacts_dir and target.agent_name in matched_set:
            _write_revert_result(
                target.artifacts_dir, target.agent_name, ordered, push=push
            )

    if push.error is not None:
        return BulkRevertResult(
            False,
            f"Reverted {len(ordered)} commit(s) across {len(matched_names)} "
            f"agent(s) locally, but push to GitHub failed: {push.error}",
            reverted_shas=ordered,
            agent_names=matched_names,
            pushed=False,
            error=f"git push failed: {push.error}",
        )

    summary = f"Reverted {len(ordered)} commit(s) across {len(matched_names)} agent(s)"
    summary += " and pushed" if push.pushed else ""
    return BulkRevertResult(
        True,
        summary,
        reverted_shas=ordered,
        agent_names=matched_names,
        pushed=push.pushed,
    )


def _apply_revert_transaction(
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
        _rollback_to(workspace_dir, head_before)
        return False, detail

    commit = _run_git(workspace_dir, ["commit", "--no-verify", "-m", message])
    if commit.returncode != 0:
        detail = (commit.stderr or commit.stdout or "git commit failed").strip()
        _rollback_to(workspace_dir, head_before)
        return False, detail

    return True, None


def _rollback_to(workspace_dir: str, head_before: str | None) -> None:
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


def _build_revert_message(
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


def _build_bulk_revert_message(
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


def _push_revert_commit(workspace_dir: str) -> _PushOutcome:
    """Push the current branch to ``origin`` when both are available.

    Skips (``attempted=False``) when there is no ``origin`` remote or no
    current branch. Otherwise runs ``git push origin <branch>`` and reports
    success or the push failure detail so callers can surface it.
    """
    remote = _run_git(workspace_dir, ["remote", "get-url", "origin"])
    if remote.returncode != 0 or not remote.stdout.strip():
        return _PushOutcome(
            attempted=False, pushed=False, skipped_reason="no origin remote"
        )
    branch = _run_git(workspace_dir, ["symbolic-ref", "--short", "HEAD"])
    branch_name = branch.stdout.strip()
    if branch.returncode != 0 or not branch_name:
        return _PushOutcome(
            attempted=False,
            pushed=False,
            skipped_reason="detached HEAD or no current branch",
        )
    push = _run_git(workspace_dir, ["push", "origin", branch_name])
    if push.returncode == 0:
        return _PushOutcome(attempted=True, pushed=True)
    detail = (push.stderr or push.stdout or "git push failed").strip()
    return _PushOutcome(attempted=True, pushed=False, error=detail)


def _write_revert_result(
    artifacts_dir: str,
    agent_name: str,
    shas: tuple[str, ...],
    *,
    push: _PushOutcome,
) -> None:
    try:
        payload: dict[str, object] = {
            "agent_name": agent_name,
            "reverted_shas": list(shas),
            "pushed": push.pushed,
            "reverted_at": datetime.now().isoformat(timespec="seconds"),
        }
        if push.error is not None:
            payload["push_error"] = push.error
        if push.skipped_reason is not None:
            payload["push_skipped_reason"] = push.skipped_reason
        path = Path(artifacts_dir) / "revert_result.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


__all__ = [
    "BulkRevertPreview",
    "BulkRevertResult",
    "RevertCommit",
    "RevertPreview",
    "RevertResult",
    "RevertTarget",
    "execute_agent_revert",
    "execute_agents_revert",
    "preview_agent_revert",
    "preview_agents_revert",
    "resolve_revert_agent_name",
    "resolve_revert_family_base",
    "resolve_revert_workspace_dir",
]

"""Backend for reverting commits associated with a done agent.

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
marked agents as a single atomic git transaction. Both paths share the same
:func:`_apply_revert_transaction` plumbing so a conflict or git failure always
rolls the worktree back to its pre-operation ``HEAD`` (the clean-worktree
precondition guarantees the hard-reset fallback only discards changes made by
the failed revert attempt).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sase.plan_chain import agent_family_base
from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags

if TYPE_CHECKING:
    from sase.ace.tui.models import Agent

_SDD_PATH_PREFIX = "sdd/"

#: How many recent commits to scan for matching ``AGENT=`` tags.
_DISCOVERY_COMMIT_LIMIT = 300

_GIT_TIMEOUT_SECONDS = 60

# Field/record separators for parsing ``git log`` output robustly even when
# commit bodies contain newlines.
_UNIT_SEP = "\x1f"
_RECORD_SEP = "\x1e"
_LOG_FORMAT = f"%H{_UNIT_SEP}%h{_UNIT_SEP}%s{_UNIT_SEP}%B{_RECORD_SEP}"


@dataclass(frozen=True)
class RevertCommit:
    """A single commit discovered as belonging to the target agent."""

    sha: str  # abbreviated SHA
    full_sha: str
    subject: str
    agent_tag: str
    changed_paths: tuple[str, ...] = ()

    @property
    def sdd_paths(self) -> tuple[str, ...]:
        """Changed paths under ``sdd/`` (prompt/plan provenance)."""
        return tuple(p for p in self.changed_paths if p.startswith(_SDD_PATH_PREFIX))


@dataclass(frozen=True)
class RevertPreview:
    """Discovered revert scope shown in the confirmation modal."""

    agent_name: str
    scope: str  # "agent" or "family"
    workspace_dir: str
    commits: tuple[RevertCommit, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when there is something safe to revert."""
        return self.error is None and bool(self.commits)

    @property
    def commit_count(self) -> int:
        return len(self.commits)

    @property
    def sdd_paths(self) -> tuple[str, ...]:
        """Distinct ``sdd/`` paths across all discovered commits, in order."""
        seen: list[str] = []
        for commit in self.commits:
            for path in commit.sdd_paths:
                if path not in seen:
                    seen.append(path)
        return tuple(seen)


@dataclass(frozen=True)
class RevertResult:
    """Outcome of an executed revert."""

    success: bool
    message: str
    reverted_shas: tuple[str, ...] = field(default_factory=tuple)
    pushed: bool = False
    error: str | None = None


@dataclass(frozen=True)
class RevertTarget:
    """One resolved agent row participating in a bulk revert.

    Carries the same metadata the single-agent path resolves up front so the
    bulk backend never has to reach back into the TUI ``Agent`` model.
    """

    agent_name: str
    display_name: str
    workspace_dir: str
    family_base: str | None = None
    artifacts_dir: str | None = None

    @property
    def scope(self) -> str:
        return "family" if self.family_base else "agent"


@dataclass(frozen=True)
class BulkRevertPreview:
    """Discovered revert scope across several marked agents.

    ``commits`` is the deduplicated, git-log newest-first combined set across
    every target. ``matched_target_names`` / ``skipped_target_names`` record
    which marked agents contributed at least one commit (for modal feedback).
    """

    workspace_dir: str
    targets: tuple[RevertTarget, ...] = ()
    commits: tuple[RevertCommit, ...] = ()
    matched_target_names: tuple[str, ...] = ()
    skipped_target_names: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when there is something safe to revert."""
        return self.error is None and bool(self.commits)

    @property
    def commit_count(self) -> int:
        return len(self.commits)

    @property
    def target_count(self) -> int:
        return len(self.targets)

    @property
    def sdd_paths(self) -> tuple[str, ...]:
        """Distinct ``sdd/`` paths across all discovered commits, in order."""
        seen: list[str] = []
        for commit in self.commits:
            for path in commit.sdd_paths:
                if path not in seen:
                    seen.append(path)
        return tuple(seen)


@dataclass(frozen=True)
class BulkRevertResult:
    """Outcome of an executed bulk revert."""

    success: bool
    message: str
    reverted_shas: tuple[str, ...] = field(default_factory=tuple)
    agent_names: tuple[str, ...] = field(default_factory=tuple)
    pushed: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Agent-derived resolution helpers
# ---------------------------------------------------------------------------


def resolve_revert_agent_name(agent: Agent) -> str | None:
    """Resolve the canonical agent name for revert provenance matching.

    Prefers the ``name`` recorded in ``agent_meta.json`` (authoritative for the
    ``AGENT=`` tag), falling back to :attr:`Agent.agent_name`.
    """
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir:
        meta_name = _agent_name_from_meta(artifacts_dir)
        if meta_name:
            return meta_name
    name = getattr(agent, "agent_name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def resolve_revert_workspace_dir(agent: Agent) -> str | None:
    """Resolve the git workspace directory the agent ran in."""
    from sase.ace.tui.widgets.prompt_panel._file_path_hints import (
        resolve_agent_workspace_dir,
    )

    return resolve_agent_workspace_dir(
        agent.effective_workspace_num,
        agent.project_file,
        agent.workspace_dir,
    )


def resolve_revert_family_base(agent: Agent, agent_name: str | None) -> str | None:
    """Resolve the agent-family base for family-scoped reverts, if any.

    Plan-chain rows carry an explicit ``agent_family``; otherwise the base is
    inferred from a family-suffixed name. ``None`` means exact selected-agent
    scope.
    """
    family = getattr(agent, "agent_family", None)
    if isinstance(family, str) and family.strip():
        return family.strip()
    if agent_name:
        return agent_family_base(agent_name)
    return None


def _agent_name_from_meta(artifacts_dir: str) -> str | None:
    try:
        meta = json.loads(
            (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(meta, dict):
        name = meta.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _discover_agent_commits(
    workspace_dir: str,
    agent_name: str,
    *,
    family_base: str | None = None,
    limit: int = _DISCOVERY_COMMIT_LIMIT,
) -> list[RevertCommit]:
    """Return commits tagged for *agent_name* (or its family), newest-first.

    Matches the exact ``AGENT=<name>`` tag line parsed from each commit
    message. When *family_base* is set, any commit whose ``AGENT`` tag shares
    that family base also matches.
    """
    log = _run_git(
        workspace_dir,
        ["log", f"-{limit}", "--no-merges", f"--format={_LOG_FORMAT}"],
    )
    if log.returncode != 0:
        return []

    commits: list[RevertCommit] = []
    for full_sha, short_sha, subject, body in _parse_log_records(log.stdout):
        tags = parse_trailing_commit_tags(body)
        agent_value = tags.get("AGENT")
        if not _agent_tag_matches(agent_value, agent_name, family_base):
            continue
        commits.append(
            RevertCommit(
                sha=short_sha,
                full_sha=full_sha,
                subject=subject,
                agent_tag=agent_value or "",
                changed_paths=tuple(_commit_changed_paths(workspace_dir, full_sha)),
            )
        )
    return commits


def _agent_tag_matches(
    tag_value: str | None,
    agent_name: str,
    family_base: str | None,
) -> bool:
    if not tag_value:
        return False
    if tag_value == agent_name:
        return True
    if family_base is not None:
        tag_base = agent_family_base(tag_value) or tag_value
        return tag_base == family_base
    return False


def _parse_log_records(stdout: str) -> list[tuple[str, str, str, str]]:
    records: list[tuple[str, str, str, str]] = []
    for raw in stdout.split(_RECORD_SEP):
        chunk = raw.lstrip("\n")
        if not chunk.strip():
            continue
        fields = chunk.split(_UNIT_SEP, 3)
        if len(fields) < 4:
            continue
        full_sha, short_sha, subject, body = fields
        records.append((full_sha.strip(), short_sha.strip(), subject, body))
    return records


def _commit_changed_paths(workspace_dir: str, full_sha: str) -> list[str]:
    out = _run_git(
        workspace_dir,
        ["diff-tree", "--no-commit-id", "--name-only", "-r", full_sha],
    )
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def _discover_bulk_commits(
    workspace_dir: str,
    targets: tuple[RevertTarget, ...],
    *,
    limit: int = _DISCOVERY_COMMIT_LIMIT,
) -> tuple[list[RevertCommit], set[str]]:
    """Scan history once and match commits against every target.

    Returns ``(commits, matched_names)`` where *commits* is deduplicated by
    full SHA (so marking both a family parent and a child cannot revert the
    same commit twice) and preserves git-log newest-first order across the
    combined set, and *matched_names* is the set of target agent names that
    matched at least one commit. A target whose only matches are commits
    already contributed by another target is still recorded as matched.
    """
    log = _run_git(
        workspace_dir,
        ["log", f"-{limit}", "--no-merges", f"--format={_LOG_FORMAT}"],
    )
    if log.returncode != 0:
        return [], set()

    commits: list[RevertCommit] = []
    matched: set[str] = set()
    seen_shas: set[str] = set()
    for full_sha, short_sha, subject, body in _parse_log_records(log.stdout):
        tags = parse_trailing_commit_tags(body)
        agent_value = tags.get("AGENT")
        if not agent_value:
            continue
        matching = [
            t
            for t in targets
            if _agent_tag_matches(agent_value, t.agent_name, t.family_base)
        ]
        if not matching:
            continue
        for target in matching:
            matched.add(target.agent_name)
        if full_sha in seen_shas:
            continue
        seen_shas.add(full_sha)
        commits.append(
            RevertCommit(
                sha=short_sha,
                full_sha=full_sha,
                subject=subject,
                agent_tag=agent_value,
                changed_paths=tuple(_commit_changed_paths(workspace_dir, full_sha)),
            )
        )
    return commits, matched


# ---------------------------------------------------------------------------
# Preview / execute
# ---------------------------------------------------------------------------


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
    if not _is_git_worktree(workspace_dir):
        return _fail("Workspace is not a git worktree (revert is git-only)")

    clean = _worktree_is_clean(workspace_dir)
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
    """Revert *shas* (newest-first) as a single revert commit.

    Re-validates a clean worktree and that every commit still exists before
    touching anything. Applies the reverts with ``git revert --no-commit`` and
    aborts cleanly on conflict/failure so the repo is never left half-reverted.
    """
    ordered = tuple(shas)
    if not ordered:
        return RevertResult(False, "No commits to revert", error="no commits")

    if not _is_git_worktree(workspace_dir):
        return RevertResult(
            False,
            "Workspace is not a git worktree (revert is git-only)",
            error="not a git worktree",
        )

    clean = _worktree_is_clean(workspace_dir)
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

    missing = [sha for sha in ordered if not _commit_exists(workspace_dir, sha)]
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

    pushed = _maybe_push(workspace_dir)
    if artifacts_dir:
        _write_revert_result(artifacts_dir, agent_name, ordered, pushed=pushed)

    summary = f"Reverted {len(ordered)} commit(s) for '{agent_name}'"
    summary += " and pushed" if pushed else ""
    return RevertResult(
        True,
        summary,
        reverted_shas=ordered,
        pushed=pushed,
    )


# ---------------------------------------------------------------------------
# Bulk preview / execute
# ---------------------------------------------------------------------------


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
    if not _is_git_worktree(workspace_dir):
        return _fail("Workspace is not a git worktree (revert is git-only)")

    clean = _worktree_is_clean(workspace_dir)
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
    """Revert a previewed bulk commit set as one atomic git transaction.

    Re-validates a clean git worktree and that every previewed commit still
    exists, then applies all reverts newest-first as a single revert commit.
    On any conflict/failure the worktree is rolled back to its pre-operation
    ``HEAD`` so no partial revert state survives. Per-agent
    ``revert_result.json`` artifacts are written only after the commit lands.
    """
    workspace_dir = preview.workspace_dir
    ordered = tuple(commit.full_sha for commit in preview.commits)
    matched_names = preview.matched_target_names or tuple(
        t.agent_name for t in preview.targets
    )

    if not ordered:
        return BulkRevertResult(False, "No commits to revert", error="no commits")

    if not _is_git_worktree(workspace_dir):
        return BulkRevertResult(
            False,
            "Workspace is not a git worktree (revert is git-only)",
            error="not a git worktree",
        )

    clean = _worktree_is_clean(workspace_dir)
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

    missing = [sha for sha in ordered if not _commit_exists(workspace_dir, sha)]
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

    pushed = _maybe_push(workspace_dir)
    matched_set = set(matched_names)
    for target in preview.targets:
        if target.artifacts_dir and target.agent_name in matched_set:
            _write_revert_result(
                target.artifacts_dir, target.agent_name, ordered, pushed=pushed
            )

    summary = f"Reverted {len(ordered)} commit(s) across {len(matched_names)} agent(s)"
    summary += " and pushed" if pushed else ""
    return BulkRevertResult(
        True,
        summary,
        reverted_shas=ordered,
        agent_names=matched_names,
        pushed=pushed,
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
    head_before = _current_head(workspace_dir)

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

    Aborts any in-progress revert sequence first, then—if the worktree was
    dirtied or ``HEAD`` advanced past the captured commit—force-resets back to
    it. Because callers require a clean-worktree precondition, the hard reset
    only discards changes introduced by the failed revert attempt. This is the
    explicit atomicity guard that ``git revert --abort`` alone does not provide.
    """
    _run_git(workspace_dir, ["revert", "--abort"])
    if head_before is None:
        return
    head_now = _current_head(workspace_dir)
    clean = _worktree_is_clean(workspace_dir)
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
        subject = _commit_subject(workspace_dir, sha)
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
        subject = _commit_subject(workspace_dir, sha)
        lines.append(f"- {sha[:9]} {subject}".rstrip())
    return "\n".join(lines)


def _maybe_push(workspace_dir: str) -> bool:
    """Push the current branch to ``origin`` when both are available."""
    remote = _run_git(workspace_dir, ["remote", "get-url", "origin"])
    if remote.returncode != 0 or not remote.stdout.strip():
        return False
    branch = _run_git(workspace_dir, ["symbolic-ref", "--short", "HEAD"])
    if branch.returncode != 0:
        return False
    branch_name = branch.stdout.strip()
    if not branch_name:
        return False
    push = _run_git(workspace_dir, ["push", "origin", branch_name])
    return push.returncode == 0


def _write_revert_result(
    artifacts_dir: str,
    agent_name: str,
    shas: tuple[str, ...],
    *,
    pushed: bool,
) -> None:
    try:
        payload = {
            "agent_name": agent_name,
            "reverted_shas": list(shas),
            "pushed": pushed,
            "reverted_at": datetime.now().isoformat(timespec="seconds"),
        }
        path = Path(artifacts_dir) / "revert_result.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# git plumbing
# ---------------------------------------------------------------------------


def _run_git(
    workspace_dir: str,
    args: list[str],
    *,
    timeout: int = _GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", workspace_dir, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(
            args, returncode=1, stdout="", stderr=str(exc)
        )


def _is_git_worktree(workspace_dir: str) -> bool:
    out = _run_git(workspace_dir, ["rev-parse", "--is-inside-work-tree"])
    return out.returncode == 0 and out.stdout.strip() == "true"


def _worktree_is_clean(workspace_dir: str) -> bool | None:
    out = _run_git(workspace_dir, ["status", "--porcelain"])
    if out.returncode != 0:
        return None
    return out.stdout.strip() == ""


def _commit_exists(workspace_dir: str, sha: str) -> bool:
    out = _run_git(workspace_dir, ["cat-file", "-e", f"{sha}^{{commit}}"])
    return out.returncode == 0


def _current_head(workspace_dir: str) -> str | None:
    out = _run_git(workspace_dir, ["rev-parse", "HEAD"])
    if out.returncode != 0:
        return None
    sha = out.stdout.strip()
    return sha or None


def _commit_subject(workspace_dir: str, sha: str) -> str:
    out = _run_git(workspace_dir, ["log", "-1", "--format=%s", sha])
    return out.stdout.strip() if out.returncode == 0 else ""


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

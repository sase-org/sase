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
"""

from __future__ import annotations

import json
import subprocess
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

    revert = _run_git(workspace_dir, ["revert", "--no-commit", "--no-edit", *ordered])
    if revert.returncode != 0:
        _run_git(workspace_dir, ["revert", "--abort"])
        detail = (revert.stderr or revert.stdout or "git revert failed").strip()
        return RevertResult(
            False,
            f"Revert failed, no changes applied: {detail}",
            error=detail,
        )

    commit = _run_git(workspace_dir, ["commit", "--no-verify", "-m", message])
    if commit.returncode != 0:
        _run_git(workspace_dir, ["revert", "--abort"])
        detail = (commit.stderr or commit.stdout or "git commit failed").strip()
        return RevertResult(
            False,
            f"Revert commit failed: {detail}",
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


def _commit_subject(workspace_dir: str, sha: str) -> str:
    out = _run_git(workspace_dir, ["log", "-1", "--format=%s", sha])
    return out.stdout.strip() if out.returncode == 0 else ""


__all__ = [
    "RevertCommit",
    "RevertPreview",
    "RevertResult",
    "execute_agent_revert",
    "preview_agent_revert",
    "resolve_revert_agent_name",
    "resolve_revert_family_base",
    "resolve_revert_workspace_dir",
]

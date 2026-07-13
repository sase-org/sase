"""Data models for Agents-tab commit reverts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

_SDD_PATH_PREFIX = "sdd/"
RevertRepoKind = Literal["linked", "external"]


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
class RevertRepo:
    """One repository workspace participating in an agent revert."""

    label: str
    workspace_dir: str
    is_primary: bool = False
    repo_kind: RevertRepoKind = "linked"
    source_agent_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepoRevertPlan:
    """Per-repository preview result."""

    repo_label: str
    workspace_dir: str
    is_primary: bool
    commits: tuple[RevertCommit, ...] = ()
    blocked_reason: str | None = None
    repo_kind: RevertRepoKind = "linked"
    discard_local_changes: bool = False
    source_agent_names: tuple[str, ...] = ()

    @property
    def revertable(self) -> bool:
        return self.blocked_reason is None and bool(
            self.commits or self.discard_local_changes
        )

    @property
    def commit_count(self) -> int:
        return len(self.commits)


@dataclass(frozen=True)
class RepoRevertOutcome:
    """Per-repository execution result."""

    repo_label: str
    workspace_dir: str
    success: bool
    reverted_shas: tuple[str, ...] = field(default_factory=tuple)
    pushed: bool = False
    error: str | None = None
    skipped_reason: str | None = None
    push_skipped_reason: str | None = None
    repo_kind: RevertRepoKind = "linked"
    discarded_local_changes: bool = False


@dataclass(frozen=True)
class RevertPreview:
    """Discovered revert scope shown in the confirmation modal."""

    agent_name: str
    scope: str  # "agent" or "family"
    workspace_dir: str
    commits: tuple[RevertCommit, ...] = ()
    repos: tuple[RepoRevertPlan, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when there is something safe to revert."""
        if self.error is not None:
            return False
        if self.repos:
            return bool(self.revertable_repos)
        return bool(self.commits)

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

    @property
    def revertable_repos(self) -> tuple[RepoRevertPlan, ...]:
        return tuple(repo for repo in self.repos if repo.revertable)

    @property
    def blocked_repos(self) -> tuple[RepoRevertPlan, ...]:
        return tuple(repo for repo in self.repos if repo.blocked_reason is not None)


@dataclass(frozen=True)
class RevertResult:
    """Outcome of an executed revert."""

    success: bool
    message: str
    reverted_shas: tuple[str, ...] = field(default_factory=tuple)
    pushed: bool = False
    error: str | None = None
    repo_outcomes: tuple[RepoRevertOutcome, ...] = field(default_factory=tuple)
    complete: bool = False


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
    repos: tuple[RepoRevertPlan, ...] = ()
    matched_target_names: tuple[str, ...] = ()
    skipped_target_names: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when there is something safe to revert."""
        if self.error is not None:
            return False
        if self.repos:
            return bool(self.revertable_repos)
        return bool(self.commits)

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

    @property
    def revertable_repos(self) -> tuple[RepoRevertPlan, ...]:
        return tuple(repo for repo in self.repos if repo.revertable)

    @property
    def blocked_repos(self) -> tuple[RepoRevertPlan, ...]:
        return tuple(repo for repo in self.repos if repo.blocked_reason is not None)


@dataclass(frozen=True)
class BulkRevertResult:
    """Outcome of an executed bulk revert."""

    success: bool
    message: str
    reverted_shas: tuple[str, ...] = field(default_factory=tuple)
    agent_names: tuple[str, ...] = field(default_factory=tuple)
    pushed: bool = False
    error: str | None = None
    repo_outcomes: tuple[RepoRevertOutcome, ...] = field(default_factory=tuple)
    complete: bool = False


@dataclass(frozen=True)
class RevertIntent:
    """Immutable revert intent captured from a single agent row.

    Carries everything the backend needs to claim a *fresh* workspace, prepare
    it on the ChangeSpec branch, and discover/execute a revert without depending
    on the directory the agent originally ran in (which can be reclaimed by
    other agents and accumulate unrelated changes).
    """

    project_file: str
    project_basename: str
    cl_name: str
    agent_name: str
    family_base: str | None = None
    artifacts_dir: str | None = None
    #: Names of linked repos the agent run touched. Re-resolved
    #: against the freshly claimed workspace number rather than reusing the
    #: agent's original linked checkouts.
    linked_repo_names: tuple[str, ...] = ()
    #: External repo marker records are kept as their original workspace-local
    #: paths. Revert cleans them in place and never fetches or re-clones.
    external_repos: tuple[RevertRepo, ...] = ()
    #: ``(source agent name, artifacts dir)`` pairs resolved in-memory by the
    #: action handler. Marker JSON is read later in the tracked worker.
    external_artifact_dirs: tuple[tuple[str, str], ...] = ()

    @property
    def scope(self) -> str:
        return "family" if self.family_base else "agent"


@dataclass(frozen=True)
class BulkRevertIntent:
    """Immutable revert intent for a bulk (marked-agent) revert.

    Bulk reverts must resolve to a single project file and a single ChangeSpec
    branch; individual agents contribute through :attr:`targets`.
    """

    project_file: str
    project_basename: str
    cl_name: str
    targets: tuple[RevertTarget, ...] = ()
    linked_repo_names: tuple[str, ...] = ()
    external_repos: tuple[RevertRepo, ...] = ()
    external_artifact_dirs: tuple[tuple[str, str], ...] = ()


__all__ = [
    "BulkRevertIntent",
    "BulkRevertPreview",
    "BulkRevertResult",
    "RepoRevertOutcome",
    "RepoRevertPlan",
    "RevertCommit",
    "RevertIntent",
    "RevertPreview",
    "RevertRepo",
    "RevertRepoKind",
    "RevertResult",
    "RevertTarget",
]

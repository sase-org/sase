"""Data models for Agents-tab commit reverts."""

from __future__ import annotations

from dataclasses import dataclass, field

_SDD_PATH_PREFIX = "sdd/"


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


__all__ = [
    "BulkRevertPreview",
    "BulkRevertResult",
    "RevertCommit",
    "RevertPreview",
    "RevertResult",
    "RevertTarget",
]

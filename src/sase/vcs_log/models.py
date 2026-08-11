"""Result models for the ``sase stitch list`` collection service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sase.core.vcs_log_wire import AggregatedCommitWire, CommitOrigin, CommitPresence
from sase.plan_documents import PlanWorkspace
from sase.vcs_provider._types import MergeVisibility
from sase.vcs_log.dates import TimeBound, VcsLogDateError

#: Internal limit sentinel meaning "fetch and aggregate without a row cap".
UNLIMITED = -1

#: Which slot of the project constellation a repo occupies.
LogRepoKind = Literal["primary", "linked", "sidecar"]


@dataclass(frozen=True)
class CommitFilters:
    """Provider-neutral commit-selection filters for ``sase stitch list``.

    ``since`` and ``until`` are epoch-second bounds. ``authors`` are
    case-insensitive substrings matched by providers against author identity
    with OR semantics.
    """

    since: int | None = None
    until: int | None = None
    authors: tuple[str, ...] = ()
    merges: MergeVisibility = "hide"
    origins: tuple[CommitOrigin, ...] = ()


@dataclass(frozen=True)
class CommitFilterSpec:
    """Stable semantic filters resolved once for each collection operation."""

    since: TimeBound | None = None
    until: TimeBound | None = None
    authors: tuple[str, ...] = ()
    merges: MergeVisibility = "hide"
    origins: tuple[CommitOrigin, ...] = ()

    def resolve(self, *, now: datetime) -> CommitFilters:
        """Resolve both date bounds against the same operation reference."""
        since = (
            self.since.resolve(now=now, boundary="since")
            if self.since is not None
            else None
        )
        until = (
            self.until.resolve(now=now, boundary="until")
            if self.until is not None
            else None
        )
        if since is not None and until is not None and since > until:
            raise VcsLogDateError(
                "--since/--after must be at or before --until/--before"
            )
        return CommitFilters(
            since=since,
            until=until,
            authors=self.authors,
            merges=self.merges,
            origins=self.origins,
        )


@dataclass(frozen=True)
class LogRepo:
    """A single repository to include in the cross-repo timeline.

    Attributes:
        name: Human-facing label (the project name for the primary repo, a
            linked-repo ``name``, or a sidecar label).
        path: Filesystem path of the repository checkout to read.
        kind: Which slot of the constellation this repo fills.
        aliases: Additional unambiguous source names accepted by ``--repo``.
        plan_workspaces: Candidate project workspaces that can own plans linked
            by commits from this repository.
    """

    name: str
    path: str
    kind: LogRepoKind
    aliases: tuple[str, ...] = ()
    plan_workspaces: tuple[PlanWorkspace, ...] = ()


@dataclass(frozen=True)
class RepoRemoteState:
    """Remote comparison state for one repository."""

    name: str
    remote_ref: str | None
    ahead: int
    behind: int
    fetched: bool
    fetched_at: float | None = None


@dataclass(frozen=True)
class VcsLogResult:
    """The resolved repos, merged timeline, and any non-fatal warnings.

    Attributes:
        repos: The repos that were successfully read (in stable display
            order: primary, then linked sorted by name, then sidecars).
        commits: The interleaved, newest-first timeline.
        warnings: Human-readable notes about repos that could not be read
            (missing checkout, non-VCS path, provider error, ...).
        remote_states: Per-repo local/remote comparison state used by
            renderers and JSON output.
        aggregate_truncated: Whether the merged candidate timeline exceeded
            its bounded aggregate cap.
        provider_truncation_possible: Whether any bounded per-repo fetch
            returned exactly its requested cap, so more candidates may exist.
        resolved_filters: Epoch filters resolved against the collection clock.
        filter_spec: Stable semantic filters used to produce
            ``resolved_filters`` when the collection originated from one.
    """

    repos: tuple[LogRepo, ...]
    commits: tuple[AggregatedCommitWire, ...]
    warnings: tuple[str, ...]
    remote_states: tuple[RepoRemoteState, ...] = ()
    aggregate_truncated: bool = False
    provider_truncation_possible: bool = False
    resolved_filters: CommitFilters | None = None
    filter_spec: CommitFilterSpec | None = None

    @property
    def potentially_truncated(self) -> bool:
        """Return whether an aggregate or provider cap may have hidden rows."""
        return self.aggregate_truncated or self.provider_truncation_possible


__all__ = [
    "UNLIMITED",
    "CommitFilterSpec",
    "CommitFilters",
    "CommitPresence",
    "LogRepo",
    "LogRepoKind",
    "RepoRemoteState",
    "VcsLogResult",
]

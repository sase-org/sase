"""Result models for the ``sase vcs log`` collection service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.core.vcs_log_wire import AggregatedCommitWire, CommitPresence

#: Internal limit sentinel meaning "fetch and aggregate without a row cap".
UNLIMITED = -1

#: Which slot of the project constellation a repo occupies.
LogRepoKind = Literal["primary", "linked", "sidecar"]


@dataclass(frozen=True)
class CommitFilters:
    """Provider-neutral commit-selection filters for ``sase vcs log``.

    ``since`` and ``until`` are epoch-second bounds. ``authors`` are
    case-insensitive substrings matched by providers against author identity
    with OR semantics.
    """

    since: int | None = None
    until: int | None = None
    authors: tuple[str, ...] = ()


@dataclass(frozen=True)
class LogRepo:
    """A single repository to include in the cross-repo timeline.

    Attributes:
        name: Human-facing label (the project name for the primary repo, a
            linked-repo ``name``, or a sidecar label).
        path: Filesystem path of the repository checkout to read.
        kind: Which slot of the constellation this repo fills.
        aliases: Additional unambiguous source names accepted by ``--repo``.
    """

    name: str
    path: str
    kind: LogRepoKind
    aliases: tuple[str, ...] = ()


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
    """

    repos: tuple[LogRepo, ...]
    commits: tuple[AggregatedCommitWire, ...]
    warnings: tuple[str, ...]
    remote_states: tuple[RepoRemoteState, ...] = ()


__all__ = [
    "UNLIMITED",
    "CommitFilters",
    "CommitPresence",
    "LogRepo",
    "LogRepoKind",
    "RepoRemoteState",
    "VcsLogResult",
]

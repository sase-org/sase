"""Result models for the ``sase vcs log`` collection service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.core.vcs_log_wire import AggregatedCommitWire

#: Which slot of the project constellation a repo occupies.
LogRepoKind = Literal["primary", "linked", "sdd"]


@dataclass(frozen=True)
class LogRepo:
    """A single repository to include in the cross-repo timeline.

    Attributes:
        name: Human-facing label (the project name for the primary repo, a
            linked-repo ``name``, or the SDD store label).
        path: Filesystem path of the repository checkout to read.
        kind: Which slot of the constellation this repo fills.
    """

    name: str
    path: str
    kind: LogRepoKind


@dataclass(frozen=True)
class VcsLogResult:
    """The resolved repos, merged timeline, and any non-fatal warnings.

    Attributes:
        repos: The repos that were successfully read (in stable display
            order: primary, then linked sorted by name, then SDD).
        commits: The interleaved, newest-first timeline.
        warnings: Human-readable notes about repos that could not be read
            (missing checkout, non-VCS path, provider error, ...).
    """

    repos: tuple[LogRepo, ...]
    commits: tuple[AggregatedCommitWire, ...]
    warnings: tuple[str, ...]


__all__ = ["LogRepo", "LogRepoKind", "VcsLogResult"]

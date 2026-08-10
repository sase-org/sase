"""Wire record for repository statistics used by ``sase stitch list``."""

from __future__ import annotations

from dataclasses import dataclass

from sase.core.vcs_log_wire import VcsCommitWire

VCS_REPO_STATS_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class VcsRepoStatsWire:
    """Provider-neutral repository stats for a single checkout.

    Attributes:
        total_commits: Total commits reachable from ``HEAD``.
        contributors: Distinct author identities, normally
            ``"Name <email>"`` values from ``git shortlog -sne HEAD``.
        last_commit: Most recent commit, or ``None`` for an empty repository.
        branch: Current branch name, or ``None`` for detached/unborn ``HEAD``.
        dirty: Whether the working tree has local changes.
    """

    total_commits: int
    contributors: tuple[str, ...]
    last_commit: VcsCommitWire | None
    branch: str | None
    dirty: bool


__all__ = [
    "VCS_REPO_STATS_WIRE_SCHEMA_VERSION",
    "VcsRepoStatsWire",
]

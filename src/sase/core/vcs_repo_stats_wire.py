"""Wire record for repository statistics used by ``sase vcs list``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.core.vcs_log_wire import VcsCommitWire, vcs_commit_from_dict

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


def vcs_repo_stats_from_dict(data: dict[str, Any]) -> VcsRepoStatsWire:
    """Rehydrate a :class:`VcsRepoStatsWire` from a JSON-safe dict."""
    raw_last = data.get("last_commit")
    last_commit = vcs_commit_from_dict(raw_last) if isinstance(raw_last, dict) else None
    raw_branch = data.get("branch")
    return VcsRepoStatsWire(
        total_commits=int(data["total_commits"]),
        contributors=tuple(str(item) for item in data.get("contributors", ())),
        last_commit=last_commit,
        branch=str(raw_branch) if raw_branch is not None else None,
        dirty=bool(data["dirty"]),
    )


__all__ = [
    "VCS_REPO_STATS_WIRE_SCHEMA_VERSION",
    "VcsRepoStatsWire",
    "vcs_repo_stats_from_dict",
]

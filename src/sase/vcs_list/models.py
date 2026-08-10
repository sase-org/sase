"""Result models for the ``sase stitch list`` service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.core.vcs_repo_stats_wire import VcsRepoStatsWire
from sase.vcs_log.models import LogRepo

DescriptionSource = Literal["config", "github"]
VcsListSort = Literal["default", "name", "commits", "recent"]


@dataclass(frozen=True)
class RepoListing:
    """Display-ready data for one resolved repository."""

    repo: LogRepo
    stats: VcsRepoStatsWire | None
    description: str | None = None
    description_source: DescriptionSource | None = None
    error: str | None = None


@dataclass(frozen=True)
class VcsListTotals:
    """Constellation-wide aggregate stats."""

    repo_count: int
    total_commits: int
    contributors: tuple[str, ...]
    latest_activity: int | None


@dataclass(frozen=True)
class VcsListResult:
    """The repos, aggregate totals, and any non-fatal warnings."""

    repos: tuple[RepoListing, ...]
    totals: VcsListTotals
    warnings: tuple[str, ...]
    color_repos: tuple[LogRepo, ...] = ()


__all__ = [
    "DescriptionSource",
    "RepoListing",
    "VcsListResult",
    "VcsListSort",
    "VcsListTotals",
]

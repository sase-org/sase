"""Surface-neutral query identity and errors for the Projects report."""

from dataclasses import dataclass
from typing import Literal

from sase.stats.ranges import StatsRange

ProjectStatsFacet = Literal["output", "code", "runs"]
ProjectStatsGrouping = Literal["project", "repo", "model", "patch"]
ALL_FACETS: frozenset[ProjectStatsFacet] = frozenset({"output", "code", "runs"})


@dataclass(frozen=True, slots=True)
class ProjectStatsQuery:
    """Resolved range and project selectors shared by the CLI and TUI.

    Fetch is a CLI preflight action; the loader itself only reads local sources.
    Grouping affects presentation and never changes the Rust query.
    """

    range: StatsRange
    project_refs: tuple[str, ...] = ()
    preset: str | None = None
    include_disabled: bool = False
    group_by: ProjectStatsGrouping | None = None
    fetch: bool = False


class ProjectStatsUsageError(ValueError):
    """A project selector or query option is invalid."""


class ProjectStatsUnavailableError(RuntimeError):
    """The binding or every requested measurement source is unavailable."""

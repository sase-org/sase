"""Snapshot loading facade over the Textual-free agent catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from sase.agents.catalog import (
    AgentCatalogLinkFacets,
    AgentCatalogRow,
    build_agent_catalog_link_facets,
    build_agent_catalog_snapshot,
)

from ...relations.artifact_links import (
    ArtifactLinksSnapshot,
    empty_artifact_links_snapshot,
    load_artifact_links_snapshot,
)

AGENTS_FIRST_PAGE_LIMIT = 500
# Kept as a compatibility alias for older callers/tests that imported it from
# the pane scaffold. The Agent pane now loads this bounded head before the
# background full-corpus extension builds the query index.
AGENTS_DEFAULT_LIMIT = AGENTS_FIRST_PAGE_LIMIT


@dataclass(frozen=True, slots=True)
class AgentsSnapshot:
    """One project-scoped view of the agent catalog."""

    project: str | None
    rows: tuple[AgentCatalogRow, ...]
    total_row_count: int
    complete: bool = True
    truncated: bool = False
    artifact_links: ArtifactLinksSnapshot = field(
        default_factory=empty_artifact_links_snapshot
    )
    link_facets: Mapping[str, AgentCatalogLinkFacets] = field(default_factory=dict)
    facets: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def load_agents_snapshot(
    project: str | None, limit: int | None = None
) -> AgentsSnapshot:
    """Build a project-scoped, newest-first catalog snapshot."""

    catalog = build_agent_catalog_snapshot()
    rows = catalog.rows
    if project is not None:
        rows = tuple(row for row in rows if row.project == project)
    # Stable secondary sort by name, then a descending sort by start time so
    # rows with no recorded start time (thin, name-only rows) sort last.
    rows = tuple(sorted(rows, key=lambda row: row.name))
    rows = tuple(sorted(rows, key=lambda row: row.started_at or "", reverse=True))
    total = len(rows)
    complete = limit is None or total <= limit
    if limit is not None:
        rows = rows[:limit]
    artifact_links = load_artifact_links_snapshot(project)
    link_facets = build_agent_catalog_link_facets(rows, artifact_links.rows)
    return AgentsSnapshot(
        project=project,
        rows=rows,
        total_row_count=total,
        complete=complete,
        # The bounded head-slice pass populates artifact_links too, rather than
        # leaving it empty until the extension pass. The aggregate is
        # project-scoped, not row-scoped, so slicing rows would not shrink it,
        # and the detail panel reads it for whichever row is highlighted first.
        # It is cheap enough to keep on first paint today -- 185 rows, ~6ms
        # cold and process-cached after (see tests/perf/README.md) -- but it is
        # a growing cost, not a constant. Move it to the extension pass if it
        # ever stops fitting inside the Agent pane's first-paint budget.
        artifact_links=artifact_links,
        link_facets=link_facets,
        facets=catalog.facets,
    )


__all__ = [
    "AGENTS_DEFAULT_LIMIT",
    "AGENTS_FIRST_PAGE_LIMIT",
    "AgentsSnapshot",
    "load_agents_snapshot",
]

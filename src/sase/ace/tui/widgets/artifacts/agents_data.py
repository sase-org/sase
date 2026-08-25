"""Snapshot loading facade over the Textual-free agent catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from sase.agents.catalog import AgentCatalogRow, build_agent_catalog_snapshot

from ...relations.artifact_links import (
    ArtifactLinksSnapshot,
    empty_artifact_links_snapshot,
    load_artifact_links_snapshot,
)

# Kept as a compatibility constant for older callers/tests that imported it
# from the pane scaffold. The Agent pane no longer caps the loaded snapshot:
# query evaluation runs over the full project-scoped corpus and ``limit:`` is
# applied only to the rendered option list.
AGENTS_DEFAULT_LIMIT = 500


@dataclass(frozen=True, slots=True)
class AgentsSnapshot:
    """One complete, project-scoped view of the agent catalog."""

    project: str | None
    rows: tuple[AgentCatalogRow, ...]
    total_row_count: int
    truncated: bool = False
    artifact_links: ArtifactLinksSnapshot = field(
        default_factory=empty_artifact_links_snapshot
    )
    facets: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def load_agents_snapshot(project: str | None) -> AgentsSnapshot:
    """Build a complete project-scoped, newest-first catalog snapshot."""

    catalog = build_agent_catalog_snapshot()
    rows = catalog.rows
    if project is not None:
        rows = tuple(row for row in rows if row.project == project)
    # Stable secondary sort by name, then a descending sort by start time so
    # rows with no recorded start time (thin, name-only rows) sort last.
    rows = tuple(sorted(rows, key=lambda row: row.name))
    rows = tuple(sorted(rows, key=lambda row: row.started_at or "", reverse=True))
    total = len(rows)
    return AgentsSnapshot(
        project=project,
        rows=rows,
        total_row_count=total,
        artifact_links=load_artifact_links_snapshot(project),
        facets=catalog.facets,
    )


__all__ = ["AGENTS_DEFAULT_LIMIT", "AgentsSnapshot", "load_agents_snapshot"]

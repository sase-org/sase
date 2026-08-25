"""Snapshot loading facade over the Textual-free agent catalog."""

from __future__ import annotations

from dataclasses import dataclass

from sase.agents.catalog import AgentCatalogRow, build_agent_catalog_snapshot

# The full catalog build (registry parse + index/archive enrichment) already
# completes in ~150-400ms on a worker thread (measured in
# ``tests/perf/bench_agent_catalog.py``), so there is no partial-then-extend
# loading pattern here the way ``files_pane`` has for its own, much larger,
# incrementally paged index. The bound below is a presentation cap only —
# per the epic's performance contract, queries evaluate across the full
# corpus and only the rendered option list is capped.
AGENTS_DEFAULT_LIMIT = 500


@dataclass(frozen=True, slots=True)
class AgentsSnapshot:
    """One project-scoped, presentation-bounded view of the agent catalog."""

    project: str | None
    rows: tuple[AgentCatalogRow, ...]
    total_row_count: int
    truncated: bool


def load_agents_snapshot(
    project: str | None,
    *,
    limit: int | None = AGENTS_DEFAULT_LIMIT,
) -> AgentsSnapshot:
    """Build a project-scoped, newest-first, presentation-bounded snapshot."""

    catalog = build_agent_catalog_snapshot()
    rows = catalog.rows
    if project is not None:
        rows = tuple(row for row in rows if row.project == project)
    # Stable secondary sort by name, then a descending sort by start time so
    # rows with no recorded start time (thin, name-only rows) sort last.
    rows = tuple(sorted(rows, key=lambda row: row.name))
    rows = tuple(sorted(rows, key=lambda row: row.started_at or "", reverse=True))
    total = len(rows)
    truncated = limit is not None and total > limit
    if limit is not None:
        rows = rows[:limit]
    return AgentsSnapshot(
        project=project,
        rows=rows,
        total_row_count=total,
        truncated=truncated,
    )


__all__ = ["AGENTS_DEFAULT_LIMIT", "AgentsSnapshot", "load_agents_snapshot"]

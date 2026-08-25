"""Textual-free agent catalog row model.

Builds one immutable :class:`AgentCatalogSnapshot` over every agent name
SASE has ever reserved, spined on the agent name registry
(``~/.sase/agent_name_registry.json``, the only complete index — the
artifact index and dismissed archive each cover a subset, and the live
Agents tab excludes dismissed agents by construction) and left-joined
against the artifact index and the dismissed-bundle archive for
enrichment. A name with neither enrichment source still becomes a row —
thin, but present — rather than being dropped.

This package has no Textual imports and is imported identically by the
Artifacts -> Agent pane (a later phase) and by ``sase agent search``, so
the row model and its query-relevant attributes exist exactly once.

Promotion trigger: promote this package to ``sase-core`` when the agent
name registry itself moves to a Rust-owned store (its writer is currently
~7,000 lines of Python in :mod:`sase.agent.names`, so a Rust reader today
would create a second schema owner for the same file), or when a third
frontend needs this row model. The registry parse is the dominant cost in
the measured build budget and is the number that would justify it if the
budget in :mod:`tests.perf.bench_agent_catalog` is ever missed.
"""

from __future__ import annotations

from ._build import build_agent_catalog_snapshot
from ._models import AgentCatalogBuildError, AgentCatalogRow, AgentCatalogSnapshot
from ._query import (
    AgentCatalogLinkFacets,
    agent_catalog_query_entries,
    agent_catalog_query_entry,
    agent_catalog_rows_query_entries,
    agent_catalog_runtime_seconds,
    agent_catalog_stable_id,
    build_agent_catalog_link_facets,
)

__all__ = [
    "AgentCatalogLinkFacets",
    "AgentCatalogBuildError",
    "AgentCatalogRow",
    "AgentCatalogSnapshot",
    "agent_catalog_query_entries",
    "agent_catalog_query_entry",
    "agent_catalog_rows_query_entries",
    "agent_catalog_runtime_seconds",
    "agent_catalog_stable_id",
    "build_agent_catalog_link_facets",
    "build_agent_catalog_snapshot",
]

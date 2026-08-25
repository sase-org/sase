"""Immutable row and snapshot types for the agent catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class AgentCatalogBuildError(RuntimeError):
    """Raised when a catalog snapshot would violate a join invariant."""


@dataclass(frozen=True, slots=True)
class AgentCatalogRow:
    """One registry name, left-joined with whatever enrichment exists for it."""

    name: str
    canonical_global_name: str | None
    kind: tuple[str, ...]
    project: str | None
    state: str | None
    family: str | None
    role: str | None
    clan: str | None
    tribe: str | None
    workflow: str | None
    parent_timestamp: str | None
    raw_suffix: str | None
    artifacts_dir: str | None
    bundle_path: str | None
    model: str | None
    llm_provider: str | None
    status: str | None
    hidden: bool
    started_at: str | None
    finished_at: float | None
    retry_attempt: int | None
    retry_of_timestamp: str | None
    retried_as_timestamp: str | None
    retry_chain_root_timestamp: str | None
    patch: str | None
    dismissed: bool
    revivable: bool
    attention: bool
    retry: bool
    has_collision_history: bool
    from_artifact_index: bool
    from_dismissed_archive: bool


@dataclass(frozen=True, slots=True)
class AgentCatalogSnapshot:
    """A complete, immutable catalog build over every registered agent name."""

    rows: tuple[AgentCatalogRow, ...]
    registry_entry_count: int
    artifact_index_row_count: int
    dismissed_summary_count: int
    enriched_count: int
    thin_count: int
    facets: Mapping[str, tuple[str, ...]]

    @property
    def enriched_ratio(self) -> float:
        """Return the fraction of rows carrying at least one enrichment source."""
        if not self.rows:
            return 0.0
        return self.enriched_count / len(self.rows)

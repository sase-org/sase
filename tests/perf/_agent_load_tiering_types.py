"""Result and row types shared by the load-tiering oracle and benchmark."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from sase.ace.tui.models import _agent_loader_artifacts as loader_artifacts

LoadPathName = Literal[
    "source_scan",
    "index_bounded",
    "index_full_history",
    "production_bounded",
    "production_full_history",
]


@dataclass(frozen=True)
class QueryBatteryCase:
    """One committed-query case the load-tier oracle should exercise."""

    query: str
    expect_query_error: bool = False


QUERY_BATTERY: tuple[QueryBatteryCase, ...] = (
    QueryBatteryCase(""),
    QueryBatteryCase("cl:feature"),
    QueryBatteryCase("model:gpt"),
    QueryBatteryCase("provider:codex"),
    QueryBatteryCase("project:gh_sase-org__sase"),
    QueryBatteryCase("kind:agent"),
    QueryBatteryCase("kind:workflow"),
    QueryBatteryCase("machine:apollo"),
    QueryBatteryCase("not machine:apollo"),
    # The legacy parser treated this as "any remote machine", but the current
    # agents-live profile rejects empty property values. Keep the battery entry
    # so a future semantics change is explicit.
    QueryBatteryCase("machine:", expect_query_error=True),
    QueryBatteryCase("feature-free-text-needle"),
    QueryBatteryCase("cl:feature AND provider:codex"),
    QueryBatteryCase("provider:codex OR model:claude"),
    QueryBatteryCase("not provider:grok"),
    QueryBatteryCase("(provider:codex OR model:claude) AND not cl:hidden"),
    QueryBatteryCase("not (provider:grok OR cl:hidden)"),
)


@dataclass(frozen=True)
class VisibleAgentRow:
    """A row identity plus the artifact location used in oracle diffs."""

    key: str
    row_id: str
    artifact_dir: str
    status: str
    hidden: bool


@dataclass(frozen=True)
class LoadPathRows:
    """Rows and timings returned by one load path."""

    name: LoadPathName
    snapshot_record_count: int
    loaded_row_count: int
    visible_rows: Mapping[str, VisibleAgentRow]
    loaded_keys: frozenset[str]
    query_error: str | None
    elapsed_ms: float
    # Only populated for the ``production_*`` paths, which load through the
    # real TUI entry point (:func:`load_tiered_agents`) and therefore have a
    # real completeness/repair verdict to inspect. The raw ``index_*`` paths
    # call the query facade directly and never produce one.
    load_state: loader_artifacts.AgentLoadState | None = None
    # Deterministic read/repair/decode counters from the raw snapshot's
    # stats; only populated for the ``source_scan``/``index_*`` paths.
    scan_stats: Mapping[str, int] | None = None

    @property
    def visible_count(self) -> int:
        return len(self.visible_rows)


@dataclass(frozen=True)
class LoadPathDiff:
    """Set difference from the authoritative source-scan visible rows."""

    name: LoadPathName
    missing: tuple[VisibleAgentRow, ...]
    visible_extra: tuple[VisibleAgentRow, ...]
    candidate_extra_keys: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.visible_extra


@dataclass(frozen=True)
class AgentLoadTieringOracleResult:
    """Full oracle result for one query string."""

    query: str
    pushdown_window_safe: bool
    pushdown_unsupported_reason: str | None
    source_scan: LoadPathRows
    index_bounded: LoadPathRows
    index_full_history: LoadPathRows
    production_bounded: LoadPathRows
    production_full_history: LoadPathRows
    diffs: Mapping[LoadPathName, LoadPathDiff]

    @property
    def query_error(self) -> str | None:
        return (
            self.source_scan.query_error
            or self.index_bounded.query_error
            or self.index_full_history.query_error
        )

    @property
    def ok(self) -> bool:
        return all(diff.ok for diff in self.diffs.values())

    def diff_for(self, name: LoadPathName) -> LoadPathDiff:
        return self.diffs[name]

"""Synthetic archive and parity oracle for Agents-tab load tiering.

The ``sase-zu`` epic changes how the Agents tab chooses artifact load
tiers. This module gives later phases a shared, real-file fixture and a
small oracle that compares loader-visible row sets across the current
source scan, bounded artifact-index query, and full-history artifact-index
query paths.

The fixture writes production-shaped marker files rather than wire objects
so the Rust scanner, SQLite index rebuild, index query, and Python
snapshot-to-Agent projection all run on their real interfaces. A few rows
carry imported-owner/source-machine provenance in marker JSON so later
phases can exercise the indexed machine candidate field.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import statistics
import time
from typing import Any, Literal

from sase.ace.tui.models import _agent_loader_artifacts as loader_artifacts
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_live_query import agent_live_query_row_id
from sase.ace.tui.models.agent_live_query_engine import apply_agents_live_query_filter
from sase.ace.tui.models.agent_live_query_pushdown import (
    compile_agents_live_query_pushdown,
)
from sase.ace.tui.models.agent_loader import (
    _load_agents_from_artifact_snapshot_sources,
    _normalize_loaded_agents,
)
from sase.core.agent_scan_facade import (
    query_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanWire,
)
from tests.perf.agent_load_tiering_fixture import (
    DEFAULT_ARCHIVE_ARTIFACT_COUNT,
    SyntheticArchiveFixture,
    build_synthetic_agent_archive,
)

_ACTIVE_LIMIT = loader_artifacts._TIER1_ACTIVE_LIMIT
_RECENT_COMPLETED_LIMIT = loader_artifacts._TIER1_RECENT_COMPLETED_LIMIT
_TUI_SCAN_OPTIONS = loader_artifacts._TUI_SCAN_OPTIONS

LoadPathName = Literal["source_scan", "index_bounded", "index_full_history"]


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


class AgentLoadTieringOracle:
    """Compare loader-visible rows across the three artifact load paths."""

    def __init__(self, fixture: SyntheticArchiveFixture) -> None:
        self.fixture = fixture

    def evaluate(
        self,
        query: str,
        *,
        requested_limit: int | None = None,
        candidate_filter_override: Mapping[str, object] | None = None,
    ) -> AgentLoadTieringOracleResult:
        pushdown = compile_agents_live_query_pushdown(query)
        if candidate_filter_override is not None:
            candidate_filter = dict(candidate_filter_override)
        else:
            candidate_filter = (
                pushdown.candidate_filter if pushdown.window_safe else None
            )

        source_scan = self._load_source_scan(query)
        index_bounded = self._load_index_bounded(
            query,
            requested_limit=requested_limit,
            candidate_filter=candidate_filter,
        )
        index_full_history = self._load_index_full_history(
            query,
            candidate_filter=candidate_filter,
        )
        diffs = {
            "index_bounded": _diff_load_path(source_scan, index_bounded),
            "index_full_history": _diff_load_path(source_scan, index_full_history),
        }
        return AgentLoadTieringOracleResult(
            query=query,
            pushdown_window_safe=pushdown.window_safe,
            pushdown_unsupported_reason=pushdown.unsupported_reason,
            source_scan=source_scan,
            index_bounded=index_bounded,
            index_full_history=index_full_history,
            diffs=diffs,
        )

    def _load_source_scan(self, query: str) -> LoadPathRows:
        return self._measure(
            "source_scan",
            query,
            lambda: scan_agent_artifacts(self.fixture.projects_root, _TUI_SCAN_OPTIONS),
        )

    def _load_index_bounded(
        self,
        query: str,
        *,
        requested_limit: int | None,
        candidate_filter: Mapping[str, object] | None,
    ) -> LoadPathRows:
        wire = AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=True,
            include_full_history=False,
            active_limit=_ACTIVE_LIMIT,
            recent_completed_limit=_RECENT_COMPLETED_LIMIT,
            include_hidden=False,
            freshness="cached",
            record_shape="list",
            window_limit=requested_limit,
            candidate_filter=dict(candidate_filter) if candidate_filter else None,
        )
        return self._measure(
            "index_bounded",
            query,
            lambda: query_agent_artifact_index(
                self.fixture.index_path,
                self.fixture.projects_root,
                wire,
                _TUI_SCAN_OPTIONS,
            ),
        )

    def _load_index_full_history(
        self,
        query: str,
        *,
        candidate_filter: Mapping[str, object] | None,
    ) -> LoadPathRows:
        wire = AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=False,
            include_full_history=True,
            active_limit=None,
            recent_completed_limit=None,
            include_hidden=False,
            freshness="cached",
            record_shape="list",
            candidate_filter=dict(candidate_filter) if candidate_filter else None,
        )
        return self._measure(
            "index_full_history",
            query,
            lambda: query_agent_artifact_index(
                self.fixture.index_path,
                self.fixture.projects_root,
                wire,
                _TUI_SCAN_OPTIONS,
            ),
        )

    def _measure(
        self,
        name: LoadPathName,
        query: str,
        load_snapshot: Any,
    ) -> LoadPathRows:
        with _temporary_sase_home(self.fixture.sase_home):
            start = time.perf_counter()
            snapshot = load_snapshot()
            agents = _agents_from_snapshot(snapshot)
            filtered, _facade, error = apply_agents_live_query_filter(query, agents)
            visible_rows = _visible_rows(filtered)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
        return LoadPathRows(
            name=name,
            snapshot_record_count=len(snapshot.records),
            loaded_row_count=len(agents),
            visible_rows=visible_rows,
            loaded_keys=frozenset(_row_key(agent) for agent in agents),
            query_error=error,
            elapsed_ms=elapsed_ms,
        )


def benchmark_load_paths(
    fixture: SyntheticArchiveFixture,
    *,
    queries: Sequence[str] = ("not machine:apollo",),
    runs: int = 5,
    warmup: int = 1,
    requested_limit: int | None = 100,
) -> dict[str, Any]:
    """Return p50/p95/max timings for every load path and query."""

    oracle = AgentLoadTieringOracle(fixture)
    query_reports: list[dict[str, Any]] = []
    totals: dict[LoadPathName, list[float]] = {
        "source_scan": [],
        "index_bounded": [],
        "index_full_history": [],
    }

    for query in queries:
        for _ in range(warmup):
            oracle.evaluate(query, requested_limit=requested_limit)
        path_samples: dict[LoadPathName, list[float]] = {
            "source_scan": [],
            "index_bounded": [],
            "index_full_history": [],
        }
        last_result: AgentLoadTieringOracleResult | None = None
        for _ in range(runs):
            last_result = oracle.evaluate(query, requested_limit=requested_limit)
            for rows in (
                last_result.source_scan,
                last_result.index_bounded,
                last_result.index_full_history,
            ):
                path_samples[rows.name].append(rows.elapsed_ms)
                totals[rows.name].append(rows.elapsed_ms)
        if last_result is None:
            continue
        query_reports.append(
            {
                "query": query,
                "query_error": last_result.query_error,
                "pushdown_window_safe": last_result.pushdown_window_safe,
                "pushdown_unsupported_reason": (
                    last_result.pushdown_unsupported_reason
                ),
                "paths": {
                    name: {
                        "timing_ms": _summarize(samples),
                        "snapshot_record_count": getattr(
                            last_result, name
                        ).snapshot_record_count,
                        "loaded_row_count": getattr(last_result, name).loaded_row_count,
                        "visible_row_count": getattr(last_result, name).visible_count,
                    }
                    for name, samples in path_samples.items()
                },
                "diffs": {
                    name: {
                        "missing_count": len(diff.missing),
                        "missing_sample": _sample_artifact_dirs(diff.missing),
                        "visible_extra_count": len(diff.visible_extra),
                        "visible_extra_sample": _sample_artifact_dirs(
                            diff.visible_extra
                        ),
                        "candidate_extra_count": len(diff.candidate_extra_keys),
                    }
                    for name, diff in last_result.diffs.items()
                },
            }
        )

    return {
        "schema_version": 1,
        "benchmark": "agent_load_tiering",
        "artifact_count": fixture.artifact_count,
        "runs": runs,
        "warmup": warmup,
        "requested_limit": requested_limit,
        "fixture": fixture.as_dict(),
        "queries": query_reports,
        "path_totals": {
            name: _summarize(samples) for name, samples in totals.items() if samples
        },
    }


def _agents_from_snapshot(snapshot: AgentArtifactScanWire) -> list[Agent]:
    agents, workflow_agent_steps = _load_agents_from_artifact_snapshot_sources(
        snapshot,
        patch_snapshot=[],
    )
    return _normalize_loaded_agents(agents, workflow_agent_steps)


def _visible_rows(agents: Iterable[Agent]) -> dict[str, VisibleAgentRow]:
    rows: dict[str, VisibleAgentRow] = {}
    for agent in agents:
        if agent.hidden or agent.is_hidden_step:
            continue
        key = _row_key(agent)
        rows[key] = VisibleAgentRow(
            key=key,
            row_id=agent_live_query_row_id(agent),
            artifact_dir=agent.index_record_dir or agent.artifacts_dir or "",
            status=agent.status,
            hidden=bool(agent.hidden or agent.is_hidden_step),
        )
    return rows


def _row_key(agent: Agent) -> str:
    artifact_dir = agent.index_record_dir or agent.artifacts_dir
    suffix = agent.prompt_step_file_name or agent_live_query_row_id(agent)
    if artifact_dir:
        return f"{artifact_dir}#{suffix}"
    return agent_live_query_row_id(agent)


def _diff_load_path(reference: LoadPathRows, candidate: LoadPathRows) -> LoadPathDiff:
    reference_keys = set(reference.visible_rows)
    candidate_keys = set(candidate.visible_rows)
    missing = tuple(
        reference.visible_rows[key] for key in sorted(reference_keys - candidate_keys)
    )
    extra = tuple(
        candidate.visible_rows[key] for key in sorted(candidate_keys - reference_keys)
    )
    candidate_extra_keys = tuple(sorted(candidate.loaded_keys - reference_keys))
    return LoadPathDiff(
        name=candidate.name,
        missing=missing,
        visible_extra=extra,
        candidate_extra_keys=candidate_extra_keys,
    )


def _summarize(values_ms: Sequence[float]) -> dict[str, float]:
    if not values_ms:
        return {
            "count": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
        }
    ordered = sorted(values_ms)
    return {
        "count": float(len(ordered)),
        "p50_ms": statistics.median(ordered),
        "p95_ms": ordered[round(0.95 * (len(ordered) - 1))],
        "max_ms": ordered[-1],
    }


def _sample_artifact_dirs(rows: Sequence[VisibleAgentRow]) -> list[str]:
    return [row.artifact_dir for row in rows[:10]]


@contextmanager
def _temporary_sase_home(sase_home: Path) -> Iterator[None]:
    previous = os.environ.get("SASE_HOME")
    os.environ["SASE_HOME"] = str(sase_home)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SASE_HOME", None)
        else:
            os.environ["SASE_HOME"] = previous


__all__ = [
    "AgentLoadTieringOracle",
    "AgentLoadTieringOracleResult",
    "DEFAULT_ARCHIVE_ARTIFACT_COUNT",
    "LoadPathDiff",
    "LoadPathRows",
    "QUERY_BATTERY",
    "QueryBatteryCase",
    "SyntheticArchiveFixture",
    "VisibleAgentRow",
    "benchmark_load_paths",
    "build_synthetic_agent_archive",
]

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

from sase.ace.dismissed_agents import (
    dismissed_bundle_identities_snapshot,
    load_dismissed_agents,
)
from sase.ace.tui.actions.agents._loading_compute import compute_apply_loaded_agents
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
    load_tiered_agents,
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


class AgentLoadTieringOracle:
    """Compare loader-visible rows across the source, index and production paths.

    ``index_bounded``/``index_full_history`` call the query facade directly
    with a harness-chosen ``freshness``, which is useful for isolating the
    index contract but is not what the TUI actually does in production (it
    forces ``revalidate`` for full-history loads and derives freshness/
    candidate filters from its own query-pushdown compilation). The
    ``production_*`` paths call :func:`load_tiered_agents`, the real TUI
    entry point, so they are the primary paths later acceptance phases
    should hold to a zero-diff bar.
    """

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
        # Unlike the two raw paths above, these never take a
        # ``candidate_filter_override``: production always derives its own
        # candidate filter from ``query``, which is the point of routing
        # through the real entry point instead of re-implementing it here.
        production_bounded = self._load_production_bounded(
            query,
            requested_limit=requested_limit,
        )
        production_full_history = self._load_production_full_history(query)
        diffs: dict[LoadPathName, LoadPathDiff] = {
            "index_bounded": _diff_load_path(source_scan, index_bounded),
            "index_full_history": _diff_load_path(source_scan, index_full_history),
            "production_bounded": _diff_load_path(source_scan, production_bounded),
            "production_full_history": _diff_load_path(
                source_scan, production_full_history
            ),
        }
        return AgentLoadTieringOracleResult(
            query=query,
            pushdown_window_safe=pushdown.window_safe,
            pushdown_unsupported_reason=pushdown.unsupported_reason,
            source_scan=source_scan,
            index_bounded=index_bounded,
            index_full_history=index_full_history,
            production_bounded=production_bounded,
            production_full_history=production_full_history,
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

    def _load_production_bounded(
        self,
        query: str,
        *,
        requested_limit: int | None,
    ) -> LoadPathRows:
        return self._measure_production(
            "production_bounded",
            query,
            full_history=False,
            requested_limit=requested_limit,
        )

    def _load_production_full_history(self, query: str) -> LoadPathRows:
        return self._measure_production(
            "production_full_history",
            query,
            full_history=True,
            requested_limit=None,
        )

    def _measure_production(
        self,
        name: LoadPathName,
        query: str,
        *,
        full_history: bool,
        requested_limit: int | None,
    ) -> LoadPathRows:
        """Load through :func:`load_tiered_agents`, the real TUI entry point.

        ``load_tiered_agents`` already applies the committed query's final
        tree-aware semantics for a bounded (Tier 1) load, but a full-history
        load intentionally skips that step (the TUI's finalize pipeline
        applies it separately once the load settles). Re-apply the same
        ``apply_agents_live_query_filter`` finalize step here so the two
        production paths are comparable.
        """
        with _temporary_sase_home(self.fixture.sase_home):
            start = time.perf_counter()
            agents, state = load_tiered_agents(
                full_history=full_history,
                search_query=query,
                requested_limit=requested_limit,
            )
            agents = _tui_visible_agents(agents)
            if full_history:
                filtered, _facade, error = apply_agents_live_query_filter(query, agents)
            else:
                filtered, error = agents, None
            visible_rows = _visible_rows(filtered)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
        return LoadPathRows(
            name=name,
            snapshot_record_count=state.record_count or 0,
            loaded_row_count=len(filtered),
            visible_rows=visible_rows,
            loaded_keys=frozenset(_row_key(agent) for agent in filtered),
            query_error=error,
            elapsed_ms=elapsed_ms,
            load_state=state,
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
            agents = _tui_visible_agents(_agents_from_snapshot(snapshot))
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
            scan_stats=_nonzero_stats(snapshot.stats),
        )


def benchmark_load_paths(
    fixture: SyntheticArchiveFixture,
    *,
    queries: Sequence[str] = ("not machine:apollo",),
    runs: int = 5,
    warmup: int = 1,
    requested_limit: int | None = 100,
    session_refreshes: int = 10,
) -> dict[str, Any]:
    """Return p50/p95/max timings, counters and speedups for every load path."""

    oracle = AgentLoadTieringOracle(fixture)
    query_reports: list[dict[str, Any]] = []
    totals: dict[LoadPathName, list[float]] = {
        "source_scan": [],
        "index_bounded": [],
        "index_full_history": [],
        "production_bounded": [],
        "production_full_history": [],
    }

    for query in queries:
        for _ in range(warmup):
            oracle.evaluate(query, requested_limit=requested_limit)
        path_samples: dict[LoadPathName, list[float]] = {
            "source_scan": [],
            "index_bounded": [],
            "index_full_history": [],
            "production_bounded": [],
            "production_full_history": [],
        }
        last_result: AgentLoadTieringOracleResult | None = None
        for _ in range(runs):
            last_result = oracle.evaluate(query, requested_limit=requested_limit)
            for rows in (
                last_result.source_scan,
                last_result.index_bounded,
                last_result.index_full_history,
                last_result.production_bounded,
                last_result.production_full_history,
            ):
                path_samples[rows.name].append(rows.elapsed_ms)
                totals[rows.name].append(rows.elapsed_ms)
        if last_result is None:
            continue
        source_p50_ms = _summarize(path_samples["source_scan"])["p50_ms"]
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
                        "counters": _path_counters(getattr(last_result, name)),
                        "speedup_vs_source_scan": _speedup(
                            source_p50_ms, _summarize(samples)["p50_ms"]
                        ),
                    }
                    for name, samples in path_samples.items()
                },
                "periodic_revalidate": _benchmark_periodic_revalidate(
                    fixture, query, runs=runs, requested_limit=requested_limit
                ),
                "refresh_session": _benchmark_refresh_session(
                    fixture,
                    query,
                    refreshes=session_refreshes,
                    requested_limit=requested_limit,
                    source_scan_p50_ms=source_p50_ms,
                ),
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
        "session_refreshes": session_refreshes,
        "fixture": fixture.as_dict(),
        "queries": query_reports,
        "path_totals": {
            name: _summarize(samples) for name, samples in totals.items() if samples
        },
    }


_LOAD_STATE_COUNTERS = (
    "marker_signatures_checked",
    "rows_repaired",
    "rows_discovered",
    "rows_removed",
    "record_json_decoded",
)


def _timed_production_load(
    query: str,
    *,
    full_history: bool,
    requested_limit: int | None,
    index_freshness: Literal["revalidate", "cached"] = "cached",
) -> tuple[float, loader_artifacts.AgentLoadState]:
    start = time.perf_counter()
    agents, state = load_tiered_agents(
        full_history=full_history,
        index_freshness=index_freshness,
        search_query=query,
        requested_limit=requested_limit,
    )
    if full_history:
        apply_agents_live_query_filter(query, agents)
    return (time.perf_counter() - start) * 1000.0, state


def _benchmark_periodic_revalidate(
    fixture: SyntheticArchiveFixture,
    query: str,
    *,
    runs: int,
    requested_limit: int | None,
) -> dict[str, Any]:
    """Time the bounded Tier 1 ``revalidate`` load periodic refreshes issue."""

    samples: list[float] = []
    state: loader_artifacts.AgentLoadState | None = None
    with _temporary_sase_home(fixture.sase_home):
        for _ in range(runs):
            elapsed_ms, state = _timed_production_load(
                query,
                full_history=False,
                requested_limit=requested_limit,
                index_freshness="revalidate",
            )
            samples.append(elapsed_ms)
    return {
        "timing_ms": _summarize(samples),
        "counters": _load_state_counters(state),
    }


def _benchmark_refresh_session(
    fixture: SyntheticArchiveFixture,
    query: str,
    *,
    refreshes: int,
    requested_limit: int | None,
    source_scan_p50_ms: float,
) -> dict[str, Any]:
    """Cost one settled unchanged-query session at loader granularity.

    The session is bounded first paint, one completed full-history upgrade,
    then ``refreshes`` ordinary cached Tier 1 refreshes. That the TUI issues
    exactly this sequence for an unchanged committed query is proven by the
    app-level query-keyed reconcile tests; this measures its cost. The
    pre-epic baseline escalated every broad refresh of an unpushable query
    to a full source scan, so it is modeled as ``refreshes + 2`` measured
    source-scan loads.
    """

    stage_samples: dict[str, list[float]] = {
        "first_paint": [],
        "full_history_upgrade": [],
        "ordinary_refresh": [],
    }
    totals: dict[str, int] = dict.fromkeys(_LOAD_STATE_COUNTERS, 0)
    full_history_reads = 0
    plan = [
        ("first_paint", False),
        ("full_history_upgrade", True),
        *(("ordinary_refresh", False) for _ in range(refreshes)),
    ]
    with _temporary_sase_home(fixture.sase_home):
        for stage, full_history in plan:
            elapsed_ms, state = _timed_production_load(
                query,
                full_history=full_history,
                requested_limit=None if full_history else requested_limit,
            )
            stage_samples[stage].append(elapsed_ms)
            full_history_reads += int(state.tier == "tier2")
            for name, value in _load_state_counters(state).items():
                totals[name] += value
    total_ms = sum(sum(samples) for samples in stage_samples.values())
    baseline_ms = source_scan_p50_ms * len(plan)
    return {
        "refreshes": refreshes,
        "full_history_reads": full_history_reads,
        "stage_timing_ms": {
            stage: _summarize(samples) for stage, samples in stage_samples.items()
        },
        "counters": totals,
        "total_ms": total_ms,
        "modeled_source_scan_session_ms": baseline_ms,
        "speedup_vs_source_scan_session": _speedup(baseline_ms, total_ms),
    }


def _load_state_counters(
    state: loader_artifacts.AgentLoadState | None,
) -> dict[str, int]:
    if state is None:
        return {}
    return {name: int(getattr(state, name)) for name in _LOAD_STATE_COUNTERS}


def _path_counters(rows: LoadPathRows) -> dict[str, int]:
    if rows.load_state is not None:
        return _load_state_counters(rows.load_state)
    return dict(rows.scan_stats or {})


def _nonzero_stats(stats: object) -> dict[str, int]:
    return {
        name: value
        for name, value in vars(stats).items()
        if isinstance(value, int) and value
    }


def _speedup(baseline_ms: float, candidate_ms: float) -> float | None:
    if candidate_ms <= 0:
        return None
    return round(baseline_ms / candidate_ms, 2)


def _tui_visible_agents(agents: list[Agent]) -> list[Agent]:
    """Apply the Agents tab's dismissal pipeline to one path's loaded rows.

    Every TUI load, source scan included, passes through
    :func:`compute_apply_loaded_agents` before display, so each path is
    compared on what the tab would show. Loader rows never come from
    dismissed bundles, so there are no recovered identities to pass.
    """
    dismissed = load_dismissed_agents()
    prep = compute_apply_loaded_agents(
        agents,
        [],
        dismissed,
        False,
        dismissed_bundle_snapshot=dismissed_bundle_identities_snapshot(),
    )
    return prep.filtered_agents


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

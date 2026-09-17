"""Benchmark harness that times every load path for a query battery."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
import time
from typing import Any, Literal

from sase.ace.tui.models import _agent_loader_artifacts as loader_artifacts
from sase.ace.tui.models.agent_live_query_engine import apply_agents_live_query_filter
from sase.ace.tui.models.agent_loader import load_tiered_agents

from tests.perf._agent_load_tiering_oracle import AgentLoadTieringOracle
from tests.perf._agent_load_tiering_rows import _temporary_sase_home
from tests.perf._agent_load_tiering_stats import (
    _LOAD_STATE_COUNTERS,
    _load_state_counters,
    _path_counters,
    _sample_artifact_dirs,
    _speedup,
    _summarize,
)
from tests.perf._agent_load_tiering_types import (
    AgentLoadTieringOracleResult,
    LoadPathName,
)
from tests.perf.agent_load_tiering_fixture import SyntheticArchiveFixture


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
    loader_artifacts._ARTIFACT_SNAPSHOT_CACHE.clear()
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
        "first_load_ms": stage_samples["first_paint"][0],
        "unchanged_refresh_ms": _summarize(stage_samples["ordinary_refresh"]),
        "stage_timing_ms": {
            stage: _summarize(samples) for stage, samples in stage_samples.items()
        },
        "counters": totals,
        "artifact_snapshot_cache": asdict(
            loader_artifacts._ARTIFACT_SNAPSHOT_CACHE.stats()
        ),
        "total_ms": total_ms,
        "modeled_source_scan_session_ms": baseline_ms,
        "speedup_vs_source_scan_session": _speedup(baseline_ms, total_ms),
    }

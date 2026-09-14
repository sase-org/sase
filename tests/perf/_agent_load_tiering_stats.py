"""Timing summaries and counter helpers for the load-tiering benchmark."""

from __future__ import annotations

from collections.abc import Sequence
import statistics

from sase.ace.tui.models import _agent_loader_artifacts as loader_artifacts

from tests.perf._agent_load_tiering_types import LoadPathRows, VisibleAgentRow

_LOAD_STATE_COUNTERS = (
    "marker_signatures_checked",
    "rows_repaired",
    "rows_discovered",
    "rows_removed",
    "record_json_decoded",
)


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


def _speedup(baseline_ms: float, candidate_ms: float) -> float | None:
    if candidate_ms <= 0:
        return None
    return round(baseline_ms / candidate_ms, 2)


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

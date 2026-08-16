"""Thin adapters for the Rust perf-log binding and telemetry fan-out."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from sase.core.rust import require_rust_binding
from sase.logs import (
    tui_agent_loads_jsonl_path,
    tui_external_tools_jsonl_path,
    tui_git_ops_jsonl_path,
    tui_launch_timing_jsonl_path,
    tui_stalls_jsonl_path,
    tui_startup_jsonl_path,
)
from sase.telemetry._config import get_telemetry_config
from sase.telemetry.query import query_range, store_stats

PerfGroupBy = Literal["subsystem", "provider", "workflow"]

_PERF_LOG_SOURCE_IDS: tuple[str, ...] = (
    "startup",
    "stalls",
    "agent_loads",
    "launch_timing",
    "git_ops",
    "external_tools",
)

_SUBSYSTEM_HISTOGRAMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sase_agent_run_duration_seconds", ()),
    ("sase_llm_invocation_duration_seconds", ()),
    ("sase_hook_duration_seconds", ()),
    ("sase_workflow_duration_seconds", ()),
    ("sase_axe_cycle_duration_seconds", ()),
)
_PROVIDER_HISTOGRAMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sase_agent_run_duration_seconds", ("llm_provider",)),
    ("sase_llm_invocation_duration_seconds", ("provider",)),
)
_WORKFLOW_HISTOGRAMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sase_agent_run_duration_seconds", ("workflow",)),
    ("sase_workflow_duration_seconds", ("workflow",)),
)

# (metric, filters, group_by, result_key)
_CounterSpec = tuple[str, dict[str, str], tuple[str, ...], str]
_SUBSYSTEM_COUNTERS: tuple[_CounterSpec, ...] = (
    ("sase_agent_runs_total", {}, (), "sase_agent_runs_total"),
    ("sase_agent_runs_total", {"status": "error"}, (), "sase_agent_runs_total:error"),
    ("sase_llm_invocations_total", {}, (), "sase_llm_invocations_total"),
    ("sase_llm_errors_total", {}, (), "sase_llm_errors_total"),
    ("sase_llm_retries_total", {}, (), "sase_llm_retries_total"),
    ("sase_hook_executions_total", {}, (), "sase_hook_executions_total"),
    ("sase_hook_retries_total", {}, (), "sase_hook_retries_total"),
    ("sase_llm_input_tokens_total", {}, (), "sase_llm_input_tokens_total"),
    ("sase_llm_output_tokens_total", {}, (), "sase_llm_output_tokens_total"),
    ("sase_llm_cache_read_tokens_total", {}, (), "sase_llm_cache_read_tokens_total"),
)
_PROVIDER_COUNTERS: tuple[_CounterSpec, ...] = (
    ("sase_agent_runs_total", {}, ("llm_provider",), "sase_agent_runs_total"),
    (
        "sase_agent_runs_total",
        {"status": "error"},
        ("llm_provider",),
        "sase_agent_runs_total:error",
    ),
    ("sase_llm_invocations_total", {}, ("provider",), "sase_llm_invocations_total"),
    ("sase_llm_errors_total", {}, ("provider",), "sase_llm_errors_total"),
    ("sase_llm_retries_total", {}, ("provider",), "sase_llm_retries_total"),
    ("sase_llm_input_tokens_total", {}, ("provider",), "sase_llm_input_tokens_total"),
    ("sase_llm_output_tokens_total", {}, ("provider",), "sase_llm_output_tokens_total"),
    (
        "sase_llm_cache_read_tokens_total",
        {},
        ("provider",),
        "sase_llm_cache_read_tokens_total",
    ),
)
_WORKFLOW_COUNTERS: tuple[_CounterSpec, ...] = (
    ("sase_agent_runs_total", {}, ("workflow",), "sase_agent_runs_total"),
    (
        "sase_agent_runs_total",
        {"status": "error"},
        ("workflow",),
        "sase_agent_runs_total:error",
    ),
)

_QUANTILES: tuple[tuple[str, float], ...] = (("p50", 0.5), ("p95", 0.95))


def query_perf_logs(
    *,
    start_ts: int,
    end_ts: int,
    paths: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    """Return the composite perf-log snapshot for one window."""
    binding = require_rust_binding("perf_logs_query")
    payload: dict[str, Any] = binding(
        {
            "start_ts": int(start_ts),
            "end_ts": int(end_ts),
            "sources": _resolve_perf_log_sources(paths),
        }
    )
    return payload


def query_perf_telemetry(
    *,
    start_ts: int,
    end_ts: int,
    group_by: PerfGroupBy = "subsystem",
) -> dict[str, Any]:
    """Fan out the fixed telemetry query set for the active Perf grouping.

    Never raises for a disabled or empty store. Grouped modes replace the
    ungrouped counterparts named in the Perf plan; they are not additive.
    """
    resolved_group = _resolve_group_by(group_by)
    config = get_telemetry_config()
    if not config.enabled:
        return {"enabled": False, "group_by": resolved_group}

    payload: dict[str, Any] = {
        "enabled": True,
        "group_by": resolved_group,
        "error": None,
        "resolution": None,
        "store": {},
        "histograms": {},
        "counters": {},
    }
    resolutions: list[str] = []
    try:
        payload["store"] = store_stats()
    except (RuntimeError, ValueError) as exc:
        payload["error"] = str(exc)

    histograms: dict[str, Any] = {}
    for metric, labels in _histogram_specs(resolved_group):
        entry: dict[str, Any] = {}
        for key, quantile in _QUANTILES:
            fetched = _query_metric(
                metric,
                start_ts=start_ts,
                end_ts=end_ts,
                kind="histogram",
                aggregation="quantile",
                quantile=quantile,
                group_by=labels,
            )
            if fetched is None:
                continue
            entry[key] = fetched
            _record_resolution(resolutions, fetched)
        fetched_max = _query_metric(
            metric,
            start_ts=start_ts,
            end_ts=end_ts,
            kind="histogram",
            aggregation="max",
            group_by=labels,
        )
        if fetched_max is not None:
            entry["max"] = fetched_max
            _record_resolution(resolutions, fetched_max)
        if entry:
            histograms[metric] = entry
    payload["histograms"] = histograms

    counters: dict[str, Any] = {}
    for metric, filters, labels, result_key in _counter_specs(resolved_group):
        fetched = _query_metric(
            metric,
            start_ts=start_ts,
            end_ts=end_ts,
            kind="counter",
            aggregation="sum",
            filters=filters,
            group_by=labels,
        )
        if fetched is None:
            continue
        counters[result_key] = fetched
        _record_resolution(resolutions, fetched)
    payload["counters"] = counters
    payload["resolution"] = _combined_resolution(resolutions)
    return payload


def _default_perf_log_path(source_id: str) -> Path:
    return {
        "startup": tui_startup_jsonl_path,
        "stalls": tui_stalls_jsonl_path,
        "agent_loads": tui_agent_loads_jsonl_path,
        "launch_timing": tui_launch_timing_jsonl_path,
        "git_ops": tui_git_ops_jsonl_path,
        "external_tools": tui_external_tools_jsonl_path,
    }[source_id]()


def _resolve_perf_log_sources(
    paths: Mapping[str, Path | str] | None,
) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for source_id in _PERF_LOG_SOURCE_IDS:
        override = None if paths is None else paths.get(source_id)
        path = (
            Path(override).expanduser()
            if override is not None
            else _default_perf_log_path(source_id)
        )
        sources.append({"id": source_id, "path": str(path)})
    return sources


def _resolve_group_by(group_by: str) -> PerfGroupBy:
    if group_by == "provider":
        return "provider"
    if group_by == "workflow":
        return "workflow"
    return "subsystem"


def _histogram_specs(group_by: PerfGroupBy) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if group_by == "provider":
        return _PROVIDER_HISTOGRAMS
    if group_by == "workflow":
        return _WORKFLOW_HISTOGRAMS
    return _SUBSYSTEM_HISTOGRAMS


def _counter_specs(group_by: PerfGroupBy) -> tuple[_CounterSpec, ...]:
    if group_by == "provider":
        return _PROVIDER_COUNTERS
    if group_by == "workflow":
        return _WORKFLOW_COUNTERS
    return _SUBSYSTEM_COUNTERS


def _query_metric(
    metric: str,
    *,
    start_ts: int,
    end_ts: int,
    kind: str,
    aggregation: str,
    quantile: float | None = None,
    filters: Mapping[str, str] | None = None,
    group_by: Sequence[str] = (),
) -> dict[str, Any] | None:
    try:
        result = query_range(
            metric,
            start_ts=int(start_ts),
            end_ts=int(end_ts),
            step_seconds=max(1, int(end_ts) - int(start_ts)),
            kind=kind,
            filters=dict(filters) if filters else None,
            group_by=tuple(group_by),
            aggregation=aggregation,
            quantile=quantile,
        )
    except (RuntimeError, ValueError):
        return None
    series_out: list[dict[str, Any]] = []
    raw_series = result.get("series", [])
    if isinstance(raw_series, (list, tuple)):
        for series in raw_series:
            collapsed = _collapse_series(
                series, aggregation=aggregation, quantile=quantile
            )
            if collapsed is not None:
                series_out.append(collapsed)
    return {
        "resolution": result.get("resolution"),
        "series": series_out,
    }


def _collapse_series(
    series: object,
    *,
    aggregation: str,
    quantile: float | None,
) -> dict[str, Any] | None:
    if not isinstance(series, Mapping):
        return None
    points = series.get("points", [])
    if not isinstance(points, (list, tuple)):
        return None
    values = [
        float(point["value"])
        for point in points
        if isinstance(point, Mapping)
        and isinstance(point.get("value"), (int, float))
        and not isinstance(point.get("value"), bool)
    ]
    if not values:
        return None
    value = max(values) if quantile is not None or aggregation == "max" else sum(values)
    labels = series.get("labels")
    return {
        "labels": dict(labels) if isinstance(labels, Mapping) else {},
        "value": value,
    }


def _record_resolution(resolutions: list[str], fetched: Mapping[str, Any]) -> None:
    resolution = fetched.get("resolution")
    if isinstance(resolution, str) and resolution:
        resolutions.append(resolution)


def _combined_resolution(resolutions: Sequence[str]) -> str | None:
    if not resolutions:
        return None
    unique = set(resolutions)
    if len(unique) == 1:
        return resolutions[0]
    return "mixed"


__all__ = ["PerfGroupBy", "query_perf_logs", "query_perf_telemetry"]

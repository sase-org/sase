"""Telemetry-backed latency sections for the Statistics Perf view."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from sase.stats._perf_view_common import delta_ratio, latency_status, percent, share
from sase.stats._view_models import PerfHeroTile, PerfLatencyRow, PerfLatencySection
from sase.stats._view_payload import (
    Payload,
    boolean,
    mapping,
    optional_number,
    text,
)
from sase.stats.perf_query import PerfGroupBy
from sase.telemetry._config import HealthThresholds

_SUBSYSTEM_ROWS: tuple[
    tuple[str, str, str, str | None, str | None, str | None], ...
] = (
    (
        "agent",
        "Agent runs",
        "sase_agent_run_duration_seconds",
        "sase_agent_runs_total",
        "sase_agent_runs_total:error",
        None,
    ),
    (
        "llm",
        "LLM calls",
        "sase_llm_invocation_duration_seconds",
        "sase_llm_invocations_total",
        "sase_llm_errors_total",
        "sase_llm_retries_total",
    ),
    (
        "hooks",
        "Hooks",
        "sase_hook_duration_seconds",
        "sase_hook_executions_total",
        None,
        "sase_hook_retries_total",
    ),
    (
        "workflows",
        "Workflows",
        "sase_workflow_duration_seconds",
        None,
        None,
        None,
    ),
    (
        "axe",
        "Axe cycles",
        "sase_axe_cycle_duration_seconds",
        None,
        None,
        None,
    ),
)


def build_latency(
    telemetry: Payload,
    previous: Payload,
    *,
    group_by: PerfGroupBy,
    thresholds: HealthThresholds,
) -> PerfLatencySection:
    """Build latency rows and headline tiles from telemetry."""
    enabled = boolean(telemetry.get("enabled"))
    if group_by == "provider":
        built_rows = _provider_rows(telemetry, thresholds)
    elif group_by == "workflow":
        built_rows = _workflow_rows(telemetry, thresholds)
    else:
        built_rows = _subsystem_rows(telemetry, thresholds)
    available = enabled and any(
        (row.count is not None and row.count > 0)
        or row.p95 is not None
        or row.p50 is not None
        for row in built_rows
    )
    agent_p95, agent_count = _agent_headline(telemetry)
    previous_agent_p95, _ = _agent_headline(previous)
    llm_p95, llm_count, llm_error_rate, llm_retry_rate = _llm_headline(telemetry)
    agent_error_rate = _agent_error_rate(telemetry)
    agent_tile = PerfHeroTile(
        key="agent_p95",
        caption="Agent p95",
        available=enabled and (agent_p95 is not None or agent_count > 0),
        value=agent_p95 if enabled else None,
        status=latency_status(agent_p95, agent_error_rate, thresholds)
        if enabled and (agent_p95 is not None or agent_error_rate is not None)
        else None,
        delta_ratio=delta_ratio(agent_p95, previous_agent_p95) if enabled else None,
        lower_is_better=True,
        sparkline=(),
        detail=f"{agent_count} runs",
        sample_count=agent_count,
    )
    llm_tile = PerfHeroTile(
        key="llm_p95",
        caption="LLM p95",
        available=enabled and (llm_p95 is not None or llm_count > 0),
        value=llm_p95 if enabled else None,
        status=latency_status(llm_p95, llm_error_rate, thresholds)
        if enabled and (llm_p95 is not None or llm_error_rate is not None)
        else None,
        delta_ratio=None,
        lower_is_better=True,
        sparkline=(),
        detail=_llm_detail(llm_error_rate, llm_retry_rate),
        sample_count=llm_count,
    )
    if not enabled:
        agent_tile = _unavailable_tile(agent_tile)
        llm_tile = _unavailable_tile(llm_tile)
        built_rows = ()
        available = False
    return PerfLatencySection(
        available=available,
        group_by=group_by,
        rows=built_rows,
        agent_tile=agent_tile,
        llm_tile=llm_tile,
    )


def _unavailable_tile(tile: PerfHeroTile) -> PerfHeroTile:
    return PerfHeroTile(
        key=tile.key,
        caption=tile.caption,
        available=False,
        value=None,
        status=None,
        delta_ratio=None,
        lower_is_better=tile.lower_is_better,
        sparkline=(),
        detail=tile.detail,
        sample_count=0,
    )


def _subsystem_rows(
    telemetry: Payload, thresholds: HealthThresholds
) -> tuple[PerfLatencyRow, ...]:
    built: list[PerfLatencyRow] = []
    for key, label, hist, count_key, error_key, retry_key in _SUBSYSTEM_ROWS:
        p50, p95, maximum = _histogram_values(telemetry, hist)
        count = int(_counter_value(telemetry, count_key)) if count_key else None
        denom = 0.0 if count is None else float(count)
        errors = _counter_value(telemetry, error_key) if error_key else 0.0
        retries = _counter_value(telemetry, retry_key) if retry_key else 0.0
        error_rate = percent(errors, denom) if error_key else None
        retry_rate = percent(retries, denom) if retry_key else None
        built.append(
            PerfLatencyRow(
                key=key,
                label=label,
                p50=p50,
                p95=p95,
                max=maximum,
                count=count,
                error_rate=error_rate,
                retry_rate=retry_rate,
                share=0.0,
                tokens_in=None,
                tokens_out=None,
                cache_read_tokens=None,
                cache_read_share=None,
                status=latency_status(
                    p95, error_rate, thresholds, retry_rate=retry_rate
                ),
            )
        )
    return tuple(built)


def _provider_rows(
    telemetry: Payload, thresholds: HealthThresholds
) -> tuple[PerfLatencyRow, ...]:
    llm_p50 = _hist_by(
        "sase_llm_invocation_duration_seconds", "p50", "provider", telemetry
    )
    llm_p95 = _hist_by(
        "sase_llm_invocation_duration_seconds", "p95", "provider", telemetry
    )
    llm_max = _hist_by(
        "sase_llm_invocation_duration_seconds", "max", "provider", telemetry
    )
    agent_p50 = _hist_by(
        "sase_agent_run_duration_seconds", "p50", "llm_provider", telemetry
    )
    agent_p95 = _hist_by(
        "sase_agent_run_duration_seconds", "p95", "llm_provider", telemetry
    )
    agent_max = _hist_by(
        "sase_agent_run_duration_seconds", "max", "llm_provider", telemetry
    )
    invocations = _count_by("sase_llm_invocations_total", "provider", telemetry)
    errors = _count_by("sase_llm_errors_total", "provider", telemetry)
    retries = _count_by("sase_llm_retries_total", "provider", telemetry)
    runs = _count_by("sase_agent_runs_total", "llm_provider", telemetry)
    tokens_in = _count_by("sase_llm_input_tokens_total", "provider", telemetry)
    tokens_out = _count_by("sase_llm_output_tokens_total", "provider", telemetry)
    cache_read = _count_by("sase_llm_cache_read_tokens_total", "provider", telemetry)
    names = sorted(
        {
            *llm_p95,
            *agent_p95,
            *invocations,
            *runs,
            *tokens_in,
            *tokens_out,
            *cache_read,
        }
    )
    built: list[PerfLatencyRow] = []
    counts = [int(invocations.get(name, runs.get(name, 0.0))) for name in names]
    total = sum(counts)
    for name, count in zip(names, counts, strict=True):
        p50 = llm_p50.get(name, agent_p50.get(name))
        p95 = llm_p95.get(name, agent_p95.get(name))
        maximum = llm_max.get(name, agent_max.get(name))
        denom = invocations.get(name, 0.0)
        error_rate = percent(errors.get(name, 0.0), denom)
        retry_rate = percent(retries.get(name, 0.0), denom)
        in_tokens = int(tokens_in.get(name, 0.0))
        out_tokens = int(tokens_out.get(name, 0.0))
        cache_tokens = int(cache_read.get(name, 0.0))
        built.append(
            PerfLatencyRow(
                key=name,
                label=name,
                p50=p50,
                p95=p95,
                max=maximum,
                count=count,
                error_rate=error_rate,
                retry_rate=retry_rate,
                share=share(count, total),
                tokens_in=in_tokens,
                tokens_out=out_tokens,
                cache_read_tokens=cache_tokens,
                cache_read_share=share(cache_tokens, in_tokens + cache_tokens),
                status=latency_status(
                    p95, error_rate, thresholds, retry_rate=retry_rate
                ),
            )
        )
    built.sort(key=lambda row: (-(row.count or 0), row.label.casefold()))
    return tuple(built)


def _workflow_rows(
    telemetry: Payload, thresholds: HealthThresholds
) -> tuple[PerfLatencyRow, ...]:
    agent_p50 = _hist_by(
        "sase_agent_run_duration_seconds", "p50", "workflow", telemetry
    )
    agent_p95 = _hist_by(
        "sase_agent_run_duration_seconds", "p95", "workflow", telemetry
    )
    agent_max = _hist_by(
        "sase_agent_run_duration_seconds", "max", "workflow", telemetry
    )
    flow_p50 = _hist_by("sase_workflow_duration_seconds", "p50", "workflow", telemetry)
    flow_p95 = _hist_by("sase_workflow_duration_seconds", "p95", "workflow", telemetry)
    flow_max = _hist_by("sase_workflow_duration_seconds", "max", "workflow", telemetry)
    runs = _count_by("sase_agent_runs_total", "workflow", telemetry)
    errors = _count_by("sase_agent_runs_total:error", "workflow", telemetry)
    names = sorted({*agent_p95, *flow_p95, *runs})
    counts = [int(runs.get(name, 0.0)) for name in names]
    total = sum(counts)
    built: list[PerfLatencyRow] = []
    for name, count in zip(names, counts, strict=True):
        p95 = agent_p95.get(name, flow_p95.get(name))
        error_rate = percent(errors.get(name, 0.0), float(count))
        built.append(
            PerfLatencyRow(
                key=name,
                label=name,
                p50=agent_p50.get(name, flow_p50.get(name)),
                p95=p95,
                max=agent_max.get(name, flow_max.get(name)),
                count=count,
                error_rate=error_rate,
                retry_rate=None,
                share=share(count, total),
                tokens_in=None,
                tokens_out=None,
                cache_read_tokens=None,
                cache_read_share=None,
                status=latency_status(p95, error_rate, thresholds),
            )
        )
    built.sort(key=lambda row: (-(row.count or 0), row.label.casefold()))
    return tuple(built)


def _agent_headline(telemetry: Payload) -> tuple[float | None, int]:
    _, p95, _ = _histogram_values(telemetry, "sase_agent_run_duration_seconds")
    count = int(_counter_value(telemetry, "sase_agent_runs_total"))
    return p95, count


def _agent_error_rate(telemetry: Payload) -> float | None:
    total = _counter_value(telemetry, "sase_agent_runs_total")
    errors = _counter_value(telemetry, "sase_agent_runs_total:error")
    return percent(errors, total)


def _llm_headline(
    telemetry: Payload,
) -> tuple[float | None, int, float | None, float | None]:
    _, p95, _ = _histogram_values(telemetry, "sase_llm_invocation_duration_seconds")
    count = _counter_value(telemetry, "sase_llm_invocations_total")
    errors = _counter_value(telemetry, "sase_llm_errors_total")
    retries = _counter_value(telemetry, "sase_llm_retries_total")
    return p95, int(count), percent(errors, count), percent(retries, count)


def _llm_detail(error_rate: float | None, retry_rate: float | None) -> str:
    err = 0.0 if error_rate is None else error_rate
    retry = 0.0 if retry_rate is None else retry_rate
    return f"err {err:.0f}% · retry {retry:.0f}%"


def _histogram_values(
    telemetry: Payload, metric: str
) -> tuple[float | None, float | None, float | None]:
    entry = mapping(mapping(telemetry.get("histograms")).get(metric))
    return (
        _first_series_value(mapping(entry.get("p50"))),
        _first_series_value(mapping(entry.get("p95"))),
        _first_series_value(mapping(entry.get("max"))),
    )


def _counter_value(telemetry: Payload, key: str) -> float:
    entry = mapping(mapping(telemetry.get("counters")).get(key))
    return _first_series_value(entry) or 0.0


def _first_series_value(entry: Payload) -> float | None:
    series = entry.get("series")
    if not isinstance(series, (list, tuple)) or not series:
        return None
    first = series[0]
    if not isinstance(first, Mapping):
        return None
    return optional_number(first.get("value"))


def _hist_by(
    metric: str, agg: str, label_key: str, telemetry: Payload
) -> dict[str, float]:
    return _labeled_values(telemetry, "histograms", metric, agg, label_key)


def _count_by(metric: str, label_key: str, telemetry: Payload) -> dict[str, float]:
    return _labeled_values(telemetry, "counters", metric, None, label_key)


def _labeled_values(
    telemetry: Payload,
    section: Literal["histograms", "counters"],
    metric: str,
    agg: str | None,
    label_key: str,
) -> dict[str, float]:
    root = mapping(telemetry.get(section))
    entry = mapping(root.get(metric))
    payload = mapping(entry.get(agg)) if agg is not None else entry
    values: dict[str, float] = {}
    series = payload.get("series")
    if not isinstance(series, (list, tuple)):
        return values
    for item in series:
        if not isinstance(item, Mapping):
            continue
        value = optional_number(item.get("value"))
        if value is None:
            continue
        labels = mapping(item.get("labels"))
        values[text(labels.get(label_key), "unknown")] = value
    return values

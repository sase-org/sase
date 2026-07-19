"""``sase telemetry health`` — one-hour local-store health assessment."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.telemetry._config import HealthThresholds, get_telemetry_config
from sase.telemetry.query import query_range

OK = "OK"
WARN = "WARN"
CRITICAL = "CRITICAL"

EXIT_HEALTHY = 0
EXIT_DEGRADED = 1
EXIT_CRITICAL = 2

_HEALTH_WINDOW_SECONDS = 60 * 60


@dataclass(frozen=True, slots=True)
class _SubsystemHealth:
    name: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class _HealthWindow:
    sample_count: int = 0
    agent_total: float = 0.0
    agent_errors: float = 0.0
    agent_p95: float = 0.0
    llm_total: float = 0.0
    llm_errors: float = 0.0
    llm_retries: float = 0.0
    input_tokens: float = 0.0
    output_tokens: float = 0.0
    axe_cycles: float = 0.0
    axe_errors: float = 0.0
    axe_restarts: float = 0.0
    hook_total: float = 0.0
    hook_retries: float = 0.0
    vcs_operations: float = 0.0
    zombie_detections: float = 0.0


def _rate(numerator: float, denominator: float) -> float:
    return numerator / denominator * 100.0 if denominator else 0.0


def _threshold_status(value: float, warn: float, critical: float) -> str:
    if value >= critical:
        return CRITICAL
    if value >= warn:
        return WARN
    return OK


def _worst(*statuses: str) -> str:
    if CRITICAL in statuses:
        return CRITICAL
    if WARN in statuses:
        return WARN
    return OK


def _assess_health(
    window: _HealthWindow, thresholds: HealthThresholds
) -> list[_SubsystemHealth]:
    """Evaluate local one-hour aggregates using the existing thresholds."""
    results: list[_SubsystemHealth] = []

    if window.agent_total > 0 or window.agent_p95 > 0:
        error_rate = _rate(window.agent_errors, window.agent_total)
        status = _worst(
            _threshold_status(
                error_rate,
                thresholds.error_rate_warn,
                thresholds.error_rate_critical,
            ),
            _threshold_status(
                window.agent_p95,
                thresholds.p95_latency_warn,
                thresholds.p95_latency_critical,
            ),
        )
        results.append(
            _SubsystemHealth(
                "Agents",
                status,
                f"error rate {error_rate:.1f}%, p95 {window.agent_p95:g}s",
            )
        )

    if window.llm_total > 0:
        error_rate = _rate(window.llm_errors, window.llm_total)
        retry_rate = _rate(window.llm_retries, window.llm_total)
        status = _worst(
            _threshold_status(
                error_rate,
                thresholds.error_rate_warn,
                thresholds.error_rate_critical,
            ),
            _threshold_status(
                retry_rate,
                thresholds.retry_rate_warn,
                thresholds.retry_rate_critical,
            ),
        )
        results.append(
            _SubsystemHealth(
                "LLM",
                status,
                f"error rate {error_rate:.1f}%, retry rate {retry_rate:.1f}%",
            )
        )

    if window.input_tokens + window.output_tokens > 0:
        results.append(
            _SubsystemHealth(
                "LLM Tokens",
                OK,
                f"{window.input_tokens:g} in / {window.output_tokens:g} out",
            )
        )

    if window.axe_cycles > 0 or window.axe_errors > 0 or window.axe_restarts > 0:
        if window.axe_errors >= 5 or window.axe_restarts >= 3:
            axe_status = CRITICAL
        elif window.axe_errors > 0 or window.axe_restarts > 0:
            axe_status = WARN
        else:
            axe_status = OK
        results.append(
            _SubsystemHealth(
                "Axe",
                axe_status,
                f"{window.axe_errors:g} errors, {window.axe_restarts:g} restarts",
            )
        )

    if window.hook_total > 0:
        retry_rate = _rate(window.hook_retries, window.hook_total)
        results.append(
            _SubsystemHealth(
                "Hooks",
                _threshold_status(
                    retry_rate,
                    thresholds.retry_rate_warn,
                    thresholds.retry_rate_critical,
                ),
                f"retry rate {retry_rate:.1f}%",
            )
        )

    if window.zombie_detections > 0:
        results.append(
            _SubsystemHealth(
                "Zombies",
                WARN,
                f"{window.zombie_detections:g} detected",
            )
        )
    if window.vcs_operations > 0:
        results.append(
            _SubsystemHealth("VCS", OK, f"{window.vcs_operations:g} operations")
        )
    return results


def _overall_status(results: list[_SubsystemHealth]) -> str:
    return _worst(*(result.status for result in results))


def _range_value(
    metric: str,
    *,
    start_ts: int,
    end_ts: int,
    filters: dict[str, str] | None = None,
    aggregation: str = "sum",
    quantile: float | None = None,
) -> tuple[float, bool]:
    kind = "histogram" if quantile is not None else "counter"
    result = query_range(
        metric,
        kind=kind,
        start_ts=start_ts,
        end_ts=end_ts,
        step_seconds=_HEALTH_WINDOW_SECONDS,
        filters=filters,
        group_by=(),
        aggregation=aggregation,
        quantile=quantile,
    )
    values = [
        float(point["value"])
        for series in result.get("series", [])
        for point in series.get("points", [])
    ]
    if not values:
        return 0.0, False
    if quantile is not None:
        return max(values), True
    return sum(values), True


def _collect_health_window(now_ts: int) -> _HealthWindow:
    start_ts = now_ts - _HEALTH_WINDOW_SECONDS
    sample_count = 0

    def counter(metric: str, filters: dict[str, str] | None = None) -> float:
        nonlocal sample_count
        value, present = _range_value(
            metric, start_ts=start_ts, end_ts=now_ts, filters=filters
        )
        sample_count += int(present)
        return value

    agent_p95, present = _range_value(
        "sase_agent_run_duration_seconds",
        start_ts=start_ts,
        end_ts=now_ts,
        aggregation="quantile",
        quantile=0.95,
    )
    sample_count += int(present)
    agent_total = counter("sase_agent_runs_total")
    agent_errors = counter("sase_agent_runs_total", {"status": "error"})
    llm_total = counter("sase_llm_invocations_total")
    llm_errors = counter("sase_llm_errors_total")
    llm_retries = counter("sase_llm_retries_total")
    input_tokens = counter("sase_llm_input_tokens_total")
    output_tokens = counter("sase_llm_output_tokens_total")
    axe_cycles = counter("sase_axe_cycles_total")
    axe_errors = counter("sase_axe_errors_total")
    axe_restarts = counter("sase_axe_lumberjack_restarts_total")
    hook_total = counter("sase_hook_executions_total")
    hook_retries = counter("sase_hook_retries_total")
    vcs_operations = counter("sase_vcs_operations_total")
    zombie_detections = counter("sase_zombie_detections_total")

    return _HealthWindow(
        sample_count=sample_count,
        agent_total=agent_total,
        agent_errors=agent_errors,
        agent_p95=agent_p95,
        llm_total=llm_total,
        llm_errors=llm_errors,
        llm_retries=llm_retries,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        axe_cycles=axe_cycles,
        axe_errors=axe_errors,
        axe_restarts=axe_restarts,
        hook_total=hook_total,
        hook_retries=hook_retries,
        vcs_operations=vcs_operations,
        zombie_detections=zombie_detections,
    )


def build_telemetry_health_payload(source: str = "auto") -> dict[str, Any]:
    """Return structured local-store health without rendering or exiting.

    ``source`` remains accepted for compatibility with ``sase doctor`` and
    third-party callers; the only source is now the configured local store.
    """
    del source
    config = get_telemetry_config()
    base: dict[str, Any] = {
        "source": "local",
        "store_path": str(config.resolved_store_path),
        "window_seconds": _HEALTH_WINDOW_SECONDS,
        "sample_count": 0,
        "subsystems": [],
    }
    if not config.enabled:
        return {**base, "status": "disabled"}
    try:
        window = _collect_health_window(int(time.time()))
    except (RuntimeError, ValueError) as exc:
        return {**base, "status": "error", "error": str(exc)}
    if window.sample_count == 0:
        return {**base, "status": "no_data"}

    results = _assess_health(window, config.health_thresholds)
    overall = _overall_status(results)
    return {
        **base,
        "status": overall.lower(),
        "sample_count": window.sample_count,
        "subsystems": [
            {
                "name": result.name,
                "status": result.status.lower(),
                "detail": result.detail,
            }
            for result in results
        ],
    }


def _status_indicator(status: str) -> Text:
    if status == CRITICAL:
        return Text("●", style="red")
    if status == WARN:
        return Text("●", style="yellow")
    return Text("●", style="green")


def _overall_label(status: str) -> Text:
    if status == CRITICAL:
        return Text("CRITICAL", style="bold red")
    if status == WARN:
        return Text("DEGRADED", style="bold yellow")
    return Text("HEALTHY", style="bold green")


def handle_telemetry_health(args: argparse.Namespace) -> None:
    """Render health and exit with 0 healthy, 1 degraded, or 2 critical."""
    use_json = bool(getattr(args, "json", False))
    console = Console()
    payload = build_telemetry_health_payload()
    status = str(payload["status"])

    if use_json:
        console.print(json.dumps(payload, indent=2, sort_keys=True))
    elif status in {"disabled", "error", "no_data"}:
        messages = {
            "disabled": "Telemetry is disabled.",
            "error": f"Unable to query telemetry: {payload.get('error', 'unknown error')}",
            "no_data": "No telemetry samples were recorded in the last hour.",
        }
        console.print(f"[red]{messages[status]}[/red]")
    else:
        lines = Text()
        for item in payload["subsystems"]:
            item_status = str(item["status"]).upper()
            lines.append("  ")
            lines.append_text(_status_indicator(item_status))
            lines.append(
                f" {str(item['name']):<16s}{item_status:<8s}({item['detail']})\n"
            )
        overall = status.upper()
        lines.append("\n  Overall: ")
        lines.append_text(_status_indicator(overall))
        lines.append(" ")
        lines.append_text(_overall_label(overall))
        lines.append("\n")
        console.print(
            Panel(lines, title="Health Check · last hour", border_style="cyan")
        )

    if status == "critical":
        sys.exit(EXIT_CRITICAL)
    if status == "warn":
        sys.exit(EXIT_DEGRADED)
    if status in {"disabled", "error", "no_data"}:
        sys.exit(EXIT_CRITICAL)
    sys.exit(EXIT_HEALTHY)


__all__ = ["build_telemetry_health_payload", "handle_telemetry_health"]

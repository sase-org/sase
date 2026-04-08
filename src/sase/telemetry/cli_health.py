"""``sase telemetry health`` — traffic-light health assessment."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.telemetry._config import HealthThresholds, get_telemetry_config
from sase.telemetry.scrape import (
    MetricSample,
    check_reachable,
    scrape,
)

# Health status levels (ordered by severity).
OK = "OK"
WARN = "WARN"
CRITICAL = "CRITICAL"

# Exit codes.
EXIT_HEALTHY = 0
EXIT_DEGRADED = 1
EXIT_CRITICAL = 2


@dataclass(frozen=True)
class _SubsystemHealth:
    """Health result for one subsystem."""

    name: str
    status: str  # OK | WARN | CRITICAL
    detail: str  # e.g. "error rate 6.7%"


def _resolve_source(source: str) -> str | None:
    """Resolve the data source URL, returning None if unreachable."""
    cfg = get_telemetry_config()
    pushgateway_url = f"http://{cfg.pushgateway_url}/metrics"
    exposition_url = f"http://localhost:{cfg.exposition_port}/metrics"

    if source == "pushgateway":
        return pushgateway_url if check_reachable(pushgateway_url) else None
    if source == "exposition":
        return exposition_url if check_reachable(exposition_url) else None

    if check_reachable(pushgateway_url):
        return pushgateway_url
    if check_reachable(exposition_url):
        return exposition_url
    return None


def _rate(numerator: float, denominator: float) -> float:
    """Compute percentage rate, returning 0.0 when denominator is zero."""
    if denominator == 0:
        return 0.0
    return (numerator / denominator) * 100.0


def _rate_status(rate: float, warn: float, critical: float) -> str:
    """Classify a rate as OK / WARN / CRITICAL."""
    if rate >= critical:
        return CRITICAL
    if rate >= warn:
        return WARN
    return OK


def _sum_by_base(samples: list[MetricSample], base_name: str) -> float:
    """Sum sample values whose name matches base_name or base_name_total."""
    total = 0.0
    targets = {base_name, base_name + "_total"}
    for s in samples:
        if s.name in targets:
            total += s.value
    return total


def _sum_by_label(
    samples: list[MetricSample], base_name: str, label: str, value: str
) -> float:
    """Sum samples matching base name and a specific label value."""
    total = 0.0
    targets = {base_name, base_name + "_total"}
    for s in samples:
        if s.name in targets and s.labels.get(label) == value:
            total += s.value
    return total


def _assess_health(
    samples: list[MetricSample], thresholds: HealthThresholds
) -> list[_SubsystemHealth]:
    """Evaluate health for each subsystem that has data."""
    results: list[_SubsystemHealth] = []

    # --- Agent Lifecycle ---
    agent_total = _sum_by_base(samples, "sase_agent_runs")
    agent_errors = _sum_by_label(samples, "sase_agent_runs", "status", "error")
    err_rate = _rate(agent_errors, agent_total)
    status = _rate_status(
        err_rate, thresholds.error_rate_warn, thresholds.error_rate_critical
    )
    if agent_total > 0:
        results.append(
            _SubsystemHealth("Agents", status, f"error rate {err_rate:.1f}%")
        )

    # --- LLM Provider ---
    llm_total = _sum_by_base(samples, "sase_llm_invocations")
    llm_errors = _sum_by_base(samples, "sase_llm_errors")
    llm_err_rate = _rate(llm_errors, llm_total)
    llm_status = _rate_status(
        llm_err_rate, thresholds.error_rate_warn, thresholds.error_rate_critical
    )
    if llm_total > 0:
        results.append(
            _SubsystemHealth("LLM", llm_status, f"error rate {llm_err_rate:.1f}%")
        )

    # --- Axe Orchestrator ---
    axe_errors = _sum_by_base(samples, "sase_axe_errors")
    axe_status = OK if axe_errors == 0 else (CRITICAL if axe_errors >= 5 else WARN)
    axe_cycles = _sum_by_base(samples, "sase_axe_cycles")
    if axe_cycles > 0 or axe_errors > 0:
        results.append(_SubsystemHealth("Axe", axe_status, f"{axe_errors:g} errors"))

    # --- Hooks ---
    hook_total = _sum_by_base(samples, "sase_hook_executions")
    hook_retries = _sum_by_base(samples, "sase_hook_retries")
    retry_rate = _rate(hook_retries, hook_total)
    hook_status = _rate_status(
        retry_rate, thresholds.retry_rate_warn, thresholds.retry_rate_critical
    )
    if hook_total > 0:
        results.append(
            _SubsystemHealth("Hooks", hook_status, f"retry rate {retry_rate:.1f}%")
        )

    # --- Beads ---
    bead_active = _sum_by_base(samples, "sase_bead_active")
    bead_ops = _sum_by_base(samples, "sase_bead_operations")
    if bead_ops > 0 or bead_active > 0:
        # "stuck" heuristic: active beads without recent transitions
        results.append(_SubsystemHealth("Beads", OK, f"{bead_active:g} active"))

    # --- VCS ---
    vcs_ops = _sum_by_base(samples, "sase_vcs_operations")
    if vcs_ops > 0:
        results.append(_SubsystemHealth("VCS", OK, f"{vcs_ops:g} operations"))

    # --- Notifications ---
    notif_sent = _sum_by_base(samples, "sase_notifications_sent")
    if notif_sent > 0:
        results.append(_SubsystemHealth("Notifications", OK, f"{notif_sent:g} sent"))

    return results


def _overall_status(results: list[_SubsystemHealth]) -> str:
    """Determine the worst status across all subsystems."""
    if any(r.status == CRITICAL for r in results):
        return CRITICAL
    if any(r.status == WARN for r in results):
        return WARN
    return OK


def _status_indicator(status: str) -> Text:
    """Return a colored bullet indicator for a health status."""
    if status == CRITICAL:
        return Text("●", style="red")
    if status == WARN:
        return Text("●", style="yellow")
    return Text("●", style="green")


def _overall_label(status: str) -> Text:
    """Return the styled overall health label."""
    if status == CRITICAL:
        return Text("CRITICAL", style="bold red")
    if status == WARN:
        return Text("DEGRADED", style="bold yellow")
    return Text("HEALTHY", style="bold green")


def handle_telemetry_health(args: argparse.Namespace) -> None:
    """Traffic-light health assessment for scripting."""
    source: str = getattr(args, "source", "auto")
    use_json: bool = getattr(args, "json", False)
    console = Console()

    url = _resolve_source(source)
    if url is None:
        if use_json:
            console.print(json.dumps({"status": "unreachable", "subsystems": []}))
        else:
            console.print(
                "[red]No metric source is reachable.[/red]\n"
                "[dim]Run 'sase telemetry status' for diagnostics.[/dim]"
            )
        sys.exit(EXIT_CRITICAL)

    samples = scrape(url)
    cfg = get_telemetry_config()
    results = _assess_health(samples, cfg.health_thresholds)
    overall = _overall_status(results)

    if use_json:
        data = {
            "status": overall.lower(),
            "subsystems": [
                {"name": r.name, "status": r.status.lower(), "detail": r.detail}
                for r in results
            ],
        }
        console.print(json.dumps(data, indent=2))
    else:
        lines = Text()
        for r in results:
            indicator = _status_indicator(r.status)
            lines.append_text(Text("  "))
            lines.append_text(indicator)
            lines.append(f" {r.name:<16s}{r.status:<8s}({r.detail})\n")

        lines.append("\n  Overall: ")
        lines.append_text(_status_indicator(overall))
        lines.append(" ")
        lines.append_text(_overall_label(overall))
        lines.append("\n")

        panel = Panel(lines, title="Health Check", border_style="cyan")
        console.print(panel)

    if overall == CRITICAL:
        sys.exit(EXIT_CRITICAL)
    elif overall == WARN:
        sys.exit(EXIT_DEGRADED)
    else:
        sys.exit(EXIT_HEALTHY)

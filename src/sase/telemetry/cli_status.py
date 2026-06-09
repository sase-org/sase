"""``sase telemetry status`` — quick health check and config display."""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.telemetry._config import get_telemetry_config
from sase.telemetry.catalog import get_catalog


def _check_reachable(url: str, timeout: float = 2.0) -> bool:
    """Return True if *url* responds to an HTTP GET within *timeout*."""
    try:
        with urllib.request.urlopen(url, timeout=timeout):  # noqa: S310
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def build_telemetry_status_payload(*, timeout: float = 2.0) -> dict[str, Any]:
    """Return structured telemetry status without rendering Rich output."""
    cfg = get_telemetry_config()
    catalog = get_catalog()
    kind_counts: dict[str, int] = {}
    for metric in catalog:
        kind_counts[metric.kind] = kind_counts.get(metric.kind, 0) + 1

    pushgateway_url = f"http://{cfg.pushgateway_url}/metrics"
    exposition_url = f"http://localhost:{cfg.exposition_port}/metrics"
    payload: dict[str, Any] = {
        "enabled": cfg.enabled,
        "metric_count": len(catalog),
        "metric_kind_counts": kind_counts,
        "pushgateway": {
            "configured_url": cfg.pushgateway_url,
            "metrics_url": pushgateway_url,
            "reachable": None,
        },
        "exposition": {
            "configured_port": cfg.exposition_port,
            "metrics_url": exposition_url,
            "reachable": None,
        },
    }
    if not cfg.enabled:
        return payload

    payload["pushgateway"]["reachable"] = _check_reachable(
        pushgateway_url, timeout=timeout
    )
    payload["exposition"]["reachable"] = _check_reachable(
        exposition_url, timeout=timeout
    )
    return payload


def handle_telemetry_status() -> None:
    """Render the telemetry status panel."""
    payload = build_telemetry_status_payload()
    console = Console()

    if not payload["enabled"]:
        panel = Panel(
            "[dim]Telemetry is disabled.\n\n"
            "Enable it in your sase.yml:\n"
            "  telemetry:\n"
            "    enabled: true[/dim]",
            title="Telemetry Status",
            border_style="dim",
        )
        console.print(panel)
        return

    total = int(payload["metric_count"])
    kind_counts = payload["metric_kind_counts"]
    breakdown = ", ".join(f"{v} {k}s" for k, v in sorted(kind_counts.items()))
    pushgateway = payload["pushgateway"]
    exposition = payload["exposition"]
    pg_ok = bool(pushgateway["reachable"])
    expo_ok = bool(exposition["reachable"])

    lines = Text()
    lines.append("  Enabled      ")
    lines.append("● yes", style="green")
    lines.append("\n  Metrics      ")
    lines.append(f"{total} registered", style="bold")
    lines.append(f" ({breakdown})")

    lines.append("\n\n  Push Gateway ")
    lines.append(f"{pushgateway['configured_url']:<20s}")
    if pg_ok:
        lines.append("● reachable", style="green")
    else:
        lines.append("○ not reachable", style="red")

    lines.append("\n  Exposition   ")
    lines.append(f"localhost:{int(exposition['configured_port']):<10d}")
    if expo_ok:
        lines.append("● running", style="green")
    else:
        lines.append("○ not running", style="red")

    panel = Panel(lines, title="Telemetry Status", border_style="cyan")
    console.print(panel)

"""``sase telemetry status`` — quick health check and config display."""

from __future__ import annotations

import urllib.error
import urllib.request

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


def handle_telemetry_status() -> None:
    """Render the telemetry status panel."""
    cfg = get_telemetry_config()
    console = Console()

    if not cfg.enabled:
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

    catalog = get_catalog()
    kind_counts: dict[str, int] = {}
    for m in catalog:
        kind_counts[m.kind] = kind_counts.get(m.kind, 0) + 1

    total = len(catalog)
    breakdown = ", ".join(f"{v} {k}s" for k, v in sorted(kind_counts.items()))

    pushgateway_url = f"http://{cfg.pushgateway_url}/metrics"
    exposition_url = f"http://localhost:{cfg.exposition_port}/metrics"

    pg_ok = _check_reachable(pushgateway_url)
    expo_ok = _check_reachable(exposition_url)

    lines = Text()
    lines.append("  Enabled      ")
    lines.append("● yes", style="green")
    lines.append("\n  Metrics      ")
    lines.append(f"{total} registered", style="bold")
    lines.append(f" ({breakdown})")

    lines.append("\n\n  Push Gateway ")
    lines.append(f"{cfg.pushgateway_url:<20s}")
    if pg_ok:
        lines.append("● reachable", style="green")
    else:
        lines.append("○ not reachable", style="red")

    lines.append("\n  Exposition   ")
    lines.append(f"localhost:{cfg.exposition_port:<10d}")
    if expo_ok:
        lines.append("● running", style="green")
    else:
        lines.append("○ not running", style="red")

    panel = Panel(lines, title="Telemetry Status", border_style="cyan")
    console.print(panel)

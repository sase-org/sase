"""``sase telemetry snapshot`` — current values from the local store."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.telemetry._config import get_telemetry_config
from sase.telemetry.catalog import SUBSYSTEM_ORDER
from sase.telemetry.query import query_snapshot, store_stats

_KIND_STYLES: dict[str, str] = {
    "counter": "cyan",
    "gauge": "yellow",
    "histogram": "magenta",
}


def _labels_text(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{key}="{value}"' for key, value in labels.items()) + "}"


def _display_value(sample: dict[str, Any]) -> str:
    value = float(sample.get("value", 0.0))
    if sample.get("kind") != "histogram":
        return f"{value:g}"
    count = int(sample.get("count", 0))
    minimum = sample.get("min")
    maximum = sample.get("max")
    bounds = ""
    if minimum is not None and maximum is not None:
        bounds = f", min={float(minimum):g}, max={float(maximum):g}"
    return f"avg={value:g}, n={count}{bounds}"


def _filter_samples(
    samples: list[dict[str, Any]], subsystem_filter: str | None
) -> list[dict[str, Any]]:
    if not subsystem_filter:
        return samples
    normalized = subsystem_filter.lower()
    return [
        sample
        for sample in samples
        if str(sample.get("subsystem", "")).lower() == normalized
    ]


def _render_rich(samples: list[dict[str, Any]], console: Console) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        grouped.setdefault(str(sample.get("subsystem", "Other")), []).append(sample)

    for subsystem in [*SUBSYSTEM_ORDER, "Other"]:
        subsystem_samples = grouped.get(subsystem, [])
        if not subsystem_samples:
            continue
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        table.add_column("Type")
        for sample in subsystem_samples:
            labels = _labels_text(dict(sample.get("labels", {})))
            kind = str(sample.get("kind", ""))
            table.add_row(
                f"{sample['metric']}{labels}",
                _display_value(sample),
                Text(kind, style=_KIND_STYLES.get(kind, "")),
            )
        console.print(
            Panel(
                table,
                title=f"{subsystem} ({len(subsystem_samples)})",
                border_style="cyan",
            )
        )


def handle_telemetry_snapshot(args: argparse.Namespace) -> None:
    """Display current values queried from the configured local store."""
    config = get_telemetry_config()
    console = Console()
    if not config.enabled:
        console.print("[yellow]Telemetry is disabled.[/yellow]")
        return

    now_ts = int(time.time())
    try:
        samples = query_snapshot(now_ts=now_ts)
        stats = store_stats()
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Unable to query the local telemetry store:[/red] {exc}")
        return

    subsystem_filter = getattr(args, "subsystem", None)
    samples = _filter_samples(samples, subsystem_filter)
    if not samples:
        if subsystem_filter:
            console.print("[dim]No metrics match the given subsystem filter.[/dim]")
        else:
            console.print(
                "[dim]No telemetry samples have been recorded yet. "
                "Normal SASE activity will populate the local store.[/dim]"
            )
        return

    if str(getattr(args, "format", "rich")) == "json":
        payload = {
            "generated_at": now_ts,
            "store_path": stats.get("store_path", str(config.resolved_store_path)),
            "samples": samples,
        }
        console.print(json.dumps(payload, indent=2, sort_keys=True))
        return
    _render_rich(samples, console)


__all__ = ["handle_telemetry_snapshot"]

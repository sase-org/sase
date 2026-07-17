"""``sase telemetry status`` — local store and flusher status."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.telemetry._config import get_telemetry_config
from sase.telemetry.catalog import get_catalog
from sase.telemetry.query import store_stats
from sase.telemetry.render import format_bytes


def build_telemetry_status_payload(*, timeout: float = 2.0) -> dict[str, Any]:
    """Return structured local telemetry status without rendering Rich output.

    ``timeout`` remains accepted for compatibility with ``sase doctor``. Local
    store reads use the configured bounded SQLite busy timeout instead.
    """
    del timeout
    config = get_telemetry_config()
    catalog = get_catalog()
    kind_counts: dict[str, int] = {}
    for metric in catalog:
        kind_counts[metric.kind] = kind_counts.get(metric.kind, 0) + 1

    payload: dict[str, Any] = {
        "enabled": config.enabled,
        "metric_count": len(catalog),
        "metric_kind_counts": kind_counts,
        "store": {
            "path": str(config.resolved_store_path),
            "db_size_bytes": 0,
            "raw_sample_count": 0,
            "rollup_5m_count": 0,
            "rollup_1h_count": 0,
            "sample_count": 0,
            "earliest_sample_ts": None,
            "latest_sample_ts": None,
            "last_write_ts": None,
            "last_write_age_seconds": None,
        },
        "flusher": {
            "state": "disabled" if not config.enabled else "idle",
            "interval_seconds": config.flush_interval_seconds,
            "last_write_age_seconds": None,
        },
        "freshness": {},
        "store_error": None,
    }
    if not config.enabled:
        return payload

    try:
        stats = store_stats()
    except (RuntimeError, ValueError) as exc:
        payload["store_error"] = str(exc)
        payload["flusher"]["state"] = "error"
        return payload

    now_ts = int(time.time())
    last_write_ts = stats.get("last_write_ts")
    last_write_age = (
        max(0, now_ts - int(last_write_ts)) if last_write_ts is not None else None
    )
    sample_count = sum(
        int(stats.get(key, 0))
        for key in ("raw_sample_count", "rollup_5m_count", "rollup_1h_count")
    )
    store = payload["store"]
    store.update(
        {
            "path": stats.get("store_path", str(config.resolved_store_path)),
            "db_size_bytes": int(stats.get("db_size_bytes", 0)),
            "raw_sample_count": int(stats.get("raw_sample_count", 0)),
            "rollup_5m_count": int(stats.get("rollup_5m_count", 0)),
            "rollup_1h_count": int(stats.get("rollup_1h_count", 0)),
            "sample_count": sample_count,
            "earliest_sample_ts": stats.get("earliest_sample_ts"),
            "latest_sample_ts": stats.get("latest_sample_ts"),
            "last_write_ts": last_write_ts,
            "last_write_age_seconds": last_write_age,
        }
    )

    if last_write_age is None:
        flusher_state = "idle"
    elif last_write_age <= max(60, int(config.flush_interval_seconds * 2)):
        flusher_state = "healthy"
    else:
        flusher_state = "stale"
    payload["flusher"].update(
        {"state": flusher_state, "last_write_age_seconds": last_write_age}
    )
    payload["freshness"] = {
        subsystem: {
            "last_write_ts": int(ts),
            "age_seconds": max(0, now_ts - int(ts)),
        }
        for subsystem, ts in dict(stats.get("last_write_by_subsystem", {})).items()
    }
    return payload


def _format_age(age: int | None) -> str:
    if age is None:
        return "never"
    if age < 60:
        return f"{age}s ago"
    if age < 3600:
        return f"{age // 60}m ago"
    if age < 86400:
        return f"{age // 3600}h ago"
    return f"{age // 86400}d ago"


def _display_path(value: object, *, max_length: int = 58) -> str:
    path = Path(str(value))
    rendered = str(path)
    if len(rendered) <= max_length:
        return rendered
    return f"…/{path.parent.name}/{path.name}"


def handle_telemetry_status() -> None:
    """Render local store, sample freshness, and inferred flusher health."""
    payload = build_telemetry_status_payload()
    console = Console()
    if not payload["enabled"]:
        console.print(
            Panel(
                "[dim]Telemetry is disabled.\n\n"
                "Enable it in your sase.yml:\n"
                "  telemetry:\n"
                "    enabled: true[/dim]",
                title="Telemetry Status",
                border_style="dim",
            )
        )
        return

    store = payload["store"]
    flusher = payload["flusher"]
    error = payload.get("store_error")
    if error:
        console.print(
            Panel(
                f"[red]Unable to open the local telemetry store:[/red]\n{error}\n\n"
                f"[dim]{store['path']}[/dim]",
                title="Telemetry Status",
                border_style="red",
            )
        )
        return

    state = str(flusher["state"])
    state_style = {"healthy": "green", "idle": "yellow", "stale": "yellow"}.get(
        state, "red"
    )
    kind_counts = payload["metric_kind_counts"]
    breakdown = ", ".join(
        f"{count} {kind}s" for kind, count in sorted(kind_counts.items())
    )
    lines = Text(overflow="fold")
    lines.append("  Enabled       ")
    lines.append("● yes", style="green")
    lines.append("\n  Metrics       ")
    lines.append(f"{payload['metric_count']} registered", style="bold")
    lines.append(f" ({breakdown})")
    lines.append("\n  Store         ")
    lines.append(_display_path(store["path"]), style="cyan")
    lines.append("\n  Size          ")
    lines.append(format_bytes(float(store["db_size_bytes"])), style="bold")
    lines.append("\n  Samples       ")
    lines.append(str(store["sample_count"]), style="bold")
    lines.append(
        f" (raw {store['raw_sample_count']}, 5m {store['rollup_5m_count']}, "
        f"1h {store['rollup_1h_count']})"
    )
    lines.append("\n  Flusher       ")
    lines.append(f"● {state}", style=state_style)
    lines.append(f" · last write {_format_age(flusher['last_write_age_seconds'])}")
    lines.append(f" · interval {float(flusher['interval_seconds']):g}s")
    console.print(Panel(lines, title="Telemetry Status", border_style="cyan"))

    freshness = payload["freshness"]
    if freshness:
        table = Table(
            "Subsystem", "Last write", show_header=True, header_style="bold", box=None
        )
        for subsystem, item in sorted(freshness.items()):
            table.add_row(subsystem, _format_age(item["age_seconds"]))
        console.print(Panel(table, title="Subsystem Freshness", border_style="cyan"))


__all__ = ["build_telemetry_status_payload", "handle_telemetry_status"]

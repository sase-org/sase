"""``sase telemetry graph`` — render one local metric as a chart."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from rich.console import Console
from rich.panel import Panel

from sase.telemetry.query import (
    RANGE_SECONDS,
    STEP_SECONDS,
    parse_group_by,
    query_range,
    resolve_metric,
    store_stats,
)
from sase.telemetry.render import Series, ValueFormat, render_line_chart


def _series_label(labels: dict[str, str], fallback: str) -> str:
    if not labels:
        return fallback
    return " · ".join(f"{key}={value}" for key, value in sorted(labels.items()))


def _value_format(metric: str) -> ValueFormat:
    if metric.endswith("_seconds"):
        return "duration"
    if "tokens" in metric:
        return "tokens"
    return "number"


def _render_graph(
    result: dict[str, Any],
    *,
    metric: str,
    width: int,
    recording_started_at: int | None,
) -> Panel:
    """Convert one Rust range result into the shared line-chart renderable."""
    aggregation = str(result.get("aggregation") or "value")
    series: list[Series] = []
    for index, item in enumerate(result.get("series", [])):
        labels = dict(item.get("labels", {}))
        label = _series_label(labels, aggregation)
        points = [
            (int(point["ts"]), float(point["value"]))
            for point in item.get("points", [])
        ]
        series.append(
            Series.from_pairs(
                f"{metric}:{index}:{sorted(labels.items())}",
                points,
                label=label,
            )
        )
    return render_line_chart(
        series,
        title=f"{metric} · {aggregation}",
        width=width,
        height=16,
        value_format=_value_format(metric),
        recording_started_at=recording_started_at,
    )


def handle_telemetry_graph(args: argparse.Namespace) -> None:
    """Query and print one pipeable local-store chart."""
    requested_metric = str(args.metric)
    resolved = resolve_metric(requested_metric)
    no_color = bool(getattr(args, "no_color", False))
    width = int(getattr(args, "width", 80))
    console = Console(no_color=no_color, highlight=False, width=max(20, width))

    if resolved is None:
        console.print(f"[red]Unknown telemetry metric:[/red] {requested_metric}")
        console.print("[dim]Run 'sase telemetry list' to see metric names.[/dim]")
        raise SystemExit(2)
    if width < 20:
        console.print("[red]Chart width must be at least 20 cells.[/red]")
        raise SystemExit(2)

    metric, kind = resolved
    range_key = str(getattr(args, "range", "1h"))
    end_ts = int(time.time())
    start_ts = end_ts - RANGE_SECONDS[range_key]
    try:
        result = query_range(
            metric,
            kind=kind,
            start_ts=start_ts,
            end_ts=end_ts,
            step_seconds=STEP_SECONDS[range_key],
            group_by=parse_group_by(getattr(args, "group_by", None)),
            aggregation=getattr(args, "aggregation", None),
        )
        stats = store_stats()
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Unable to query telemetry:[/red] {exc}")
        raise SystemExit(2) from exc

    console.print(
        _render_graph(
            result,
            metric=metric,
            width=width,
            recording_started_at=stats.get("earliest_sample_ts"),
        )
    )


__all__ = ["handle_telemetry_graph"]

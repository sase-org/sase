"""Presentation for the Statistics pane's Footprint map and lens rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from sase.footprint.render import (
    area_row_text,
    feature_row_text,
    header_chip,
    header_text,
    legend_text,
)
from sase.stats.loader import StatisticsViewData
from sase.stats.registry import statistics_group_label

_ACCENT = "#FF87D7"
_CYAN = "#87D7FF"


def footprint_renderable(pane: Any, result: StatisticsViewData) -> Group:
    """Render trust, the selected lens, and a keyboard-navigable row list."""
    report = result.footprint
    if report is None:
        return Group(Text("Loading Footprint", style="dim italic"))

    header = Group(header_text(report), header_chip(report))
    tiles = report.get("tiles", {})
    tiles = tiles if isinstance(tiles, Mapping) else {}
    total = max(0, int(tiles.get("total", 0) or 0))
    if total == 0:
        body = Panel(
            Align.center(
                Group(
                    Text("No Footprint catalog has been ingested yet.", style="bold"),
                    Text(
                        "Without catalog rows, the view cannot distinguish "
                        "untracked features from no recorded use.",
                        style="dim",
                    ),
                    Text("Refresh after the next Footprint fold.", style=_CYAN),
                ),
                vertical="middle",
            ),
            title="Catalog unavailable",
            border_style=_CYAN,
            height=max(8, int(pane.size.height or 24) - 12),
        )
        return Group(header, body)

    items = pane._footprint_items(report)
    if items:
        pane._footprint_selected_index = min(
            max(0, pane._footprint_selected_index), len(items) - 1
        )
        lines: list[Text] = []
        strip_width = max(8, min(32, int(pane.size.width or 100) - 70))
        show_areas = pane._footprint_lens == "map" and pane._footprint_area is None
        show_coverage = (
            pane._footprint_lens == "coverage" and pane._footprint_area is None
        )
        for index, item in enumerate(items):
            if show_areas:
                row = area_row_text(item, strip_width=strip_width)
            elif show_coverage:
                row = _coverage_row_text(item)
            else:
                row = feature_row_text(item)
            line = Text("❯ " if index == pane._footprint_selected_index else "  ")
            line.append_text(row)
            if index == pane._footprint_selected_index:
                line.stylize("on #253044")
            lines.append(line)
        rows: Any = Group(*lines)
    else:
        pane._footprint_selected_index = 0
        if pane._footprint_area is not None:
            empty_message = f"No features recorded in {pane._footprint_area}."
        else:
            label = statistics_group_label("footprint", pane._footprint_lens)
            empty_message = f"No {label.lower()} rows for this actor and range."
        rows = Align.center(
            Group(
                Text(empty_message, style="dim italic"),
                Text("Try another lens or actor, or widen the range.", style="dim"),
            ),
            vertical="middle",
        )

    if pane._footprint_area is not None:
        title = f"Features · {pane._footprint_area}"
    elif pane._footprint_lens == "map":
        title = "Surface map"
    else:
        label = statistics_group_label("footprint", pane._footprint_lens)
        title = f"{label} lens"
    body = Panel(
        rows,
        title=title,
        border_style=_ACCENT,
        padding=(0, 1),
    )
    if pane._footprint_lens == "map" and pane._footprint_area is None:
        legend = Text(
            "█ ≤7d  ▓ ≤30d  ▒ ≤window  · no recorded use  ? not measured",
            style="dim",
        )
    elif pane._footprint_lens == "coverage" and pane._footprint_area is None:
        legend = Text(
            "Measured = observed days  · active = days with use  · "
            "torn / dropped / unknown / incomplete = data quality signals",
            style="dim",
        )
    else:
        legend = legend_text()
    return Group(header, body, legend)


def _coverage_row_text(row: Mapping[str, Any]) -> Text:
    """Show coverage and collector-quality counts without implying usage zeros."""
    text = Text()
    text.append(str(row.get("surface", "unknown")), style="bold")
    text.append(f"  {int(row.get('measured_days', 0) or 0)} measured", style="dim")
    text.append(f"  {int(row.get('active_days', 0) or 0)} active", style="dim")
    for label, key in (
        ("torn", "torn"),
        ("dropped", "dropped"),
        ("unknown", "unknown_ids"),
        ("incomplete", "incomplete_days"),
    ):
        count = int(row.get(key, 0) or 0)
        if count:
            text.append(
                f"  {label} {count}", style=_CYAN if label == "incomplete" else "dim"
            )
    return text


__all__ = ["footprint_renderable"]

"""Presentation for the Statistics pane's Footprint map and lens rows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.align import Align
from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from sase.footprint.render import (
    area_card_panel,
    area_row_text,
    card_panel,
    feature_row_text,
    header_chip,
    header_text,
    legend_text,
)
from sase.footprint.render._styles import MUTED_STYLE, STATE_GLYPHS
from sase.stats.loader import StatisticsViewData
from sase.stats.registry import statistics_group_label

_ACCENT = "#FF87D7"
_CYAN = "#87D7FF"

#: At this width and above the evidence card sits beside the row list.
_WIDE_CARD_BELOW_WIDTH = 120


def fetch_footprint_card(
    target: tuple[str, str],
    *,
    actor: str,
    window_days: int | None,
    today: str,
) -> dict[str, Any]:
    """Run ``footprint_card`` off the event loop; tests monkeypatch this seam."""
    from sase.footprint.query import build_card_request, fetch_card

    _kind, name = target
    return fetch_card(
        build_card_request(
            target=name, actor=actor, window_days=window_days, today=today
        )
    )


def footprint_renderable(pane: Any, result: StatisticsViewData) -> Group:
    """Render trust, the selected lens, rows, and the responsive evidence card."""
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
        return Group(header, body, _legend(pane))

    width = max(40, int(pane.size.width or 100))
    narrow = width < _WIDE_CARD_BELOW_WIDTH
    items = pane._footprint_items(report)
    if items:
        pane._footprint_selected_index = min(
            max(0, pane._footprint_selected_index), len(items) - 1
        )
        lines = _row_lines(pane, items, narrow=narrow, width=width)
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
    list_panel = Panel(
        rows,
        title=title,
        border_style=_ACCENT,
        padding=(0, 1),
    )
    card = _card_renderable(pane, report)
    if card is None:
        return Group(header, list_panel, _legend(pane))
    if narrow:
        return Group(header, list_panel, card, _legend(pane))
    return Group(
        header,
        Columns([list_panel, card], equal=True, expand=True),
        _legend(pane),
    )


def _legend(pane: Any) -> Text:
    """Return the glyph key for the active lens."""
    if pane._footprint_lens == "map" and pane._footprint_area is None:
        return Text(
            "█ ≤7d  ▓ ≤30d  ▒ ≤window  · no recorded use  ? not measured",
            style="dim",
        )
    if pane._footprint_lens == "coverage" and pane._footprint_area is None:
        return Text(
            "Measured = observed days  ·  active = days with use  · "
            "torn / dropped / unknown / incomplete = data quality signals",
            style="dim",
        )
    return legend_text()


def _row_lines(
    pane: Any, items: tuple[dict[str, Any], ...], *, narrow: bool, width: int
) -> list[Text]:
    """Render one selectable line per row, hiding secondary detail when narrow."""
    lines: list[Text] = []
    show_areas = pane._footprint_lens == "map" and pane._footprint_area is None
    show_coverage = pane._footprint_lens == "coverage" and pane._footprint_area is None
    strip_width = max(8, min(32, width - 70)) if not narrow else 0
    for index, item in enumerate(items):
        if show_areas:
            row = (
                _compact_area_row_text(item)
                if narrow
                else area_row_text(item, strip_width=strip_width)
            )
        elif show_coverage:
            row = _coverage_row_text(item)
        elif narrow:
            row = _compact_feature_row_text(item)
        else:
            row = feature_row_text(item)
        line = Text("❯ " if index == pane._footprint_selected_index else "  ")
        line.append_text(row)
        if index == pane._footprint_selected_index:
            line.stylize("on #253044")
        lines.append(line)
    return lines


def _compact_feature_row_text(row: Mapping[str, Any]) -> Text:
    """Return one feature row with secondary columns hidden for narrow panes."""
    state = str(row.get("state", ""))
    glyph, color = STATE_GLYPHS.get(state, ("·", MUTED_STYLE))
    text = Text()
    text.append(f"{glyph} ", style=color)
    text.append(str(row.get("label", "")), style="bold")
    text.append(f" `{row.get('id', '')}`", style=MUTED_STYLE)
    uses = row.get("uses", {})
    if isinstance(uses, dict):
        parts = [
            f"{name} {uses.get(name, 0)}" for name in ("human", "agent", "automation")
        ]
        text.append(f"  {' · '.join(parts)}", style=MUTED_STYLE)
    text.append(f"  {int(row.get('days_used', 0) or 0)}d used", style=MUTED_STYLE)
    if bool(row.get("coverage_incomplete", False)):
        text.append("  incomplete", style="dim")
    return text


def _compact_area_row_text(area: Mapping[str, Any]) -> Text:
    """Return one map area row without the heat strip for narrow panes."""
    total = max(0, int(area.get("total", 0) or 0))
    used = max(0, int(area.get("used", 0) or 0))
    pct = int(area.get("used_pct", 0) or 0)
    text = Text()
    text.append(str(area.get("area", "")), style="bold")
    text.append(f"  {used}/{total}  {pct}%", style=MUTED_STYLE)
    if total > 0 and used / total < 0.25:
        text.append("  ◂", style="dim")
    return text


def _card_renderable(pane: Any, report: Mapping[str, Any]) -> RenderableType | None:
    """Return the evidence card for the current selection, if it has one."""
    target = pane._footprint_card_target()
    if target is None:
        return None
    card = pane._footprint_card
    header = dict(report.get("header", {}))
    if isinstance(card, Mapping) and pane._footprint_card_for == target:
        kind, _name = target
        return _card_panel(dict(card), header, area=kind == "area")
    if pane._footprint_card_error and pane._footprint_card is None:
        return Panel(
            Group(
                Text("Evidence unavailable.", style="bold"),
                Text(str(pane._footprint_card_error), style="dim"),
                Text("The row list above is unaffected.", style="dim"),
            ),
            title="Evidence",
            border_style="red",
            padding=(1, 2),
        )
    return Panel(
        Text("Loading evidence…", style="dim italic"),
        title="Evidence",
        border_style="#444444",
        padding=(1, 2),
    )


def _card_panel(card: dict[str, Any], header: dict[str, Any], *, area: bool) -> Panel:
    """Dispatch a fetched card to the area summary or feature evidence panel."""
    summary = card.get("area_summary")
    if area and isinstance(summary, Mapping):
        return area_card_panel(dict(summary), header)
    return card_panel(card, header)


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


__all__ = ["fetch_footprint_card", "footprint_renderable"]

"""Rich renderables shared by the CLI and the TUI Footprint view."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.footprint.render._heat import heat_strip
from sase.footprint.render._styles import (
    COLD_MARKER,
    DECISION_BADGES,
    FAULT_STYLE,
    MUTED_STYLE,
    NOT_MEASURED_GLYPH,
    PREVIEW_STYLE,
    RECENT_7D_STYLE,
    STATE_GLYPHS,
    STATE_LABELS,
)
from sase.stats.render.primitives import format_count
from sase.telemetry.render.sparkline import SPARK_BLOCKS
from sase.telemetry.render.tiles import render_stat_tile

_SURFACES = ("cli", "tui", "macro", "skill", "config", "auto", "plugin")


def surface_for_ns(ns: str) -> str:
    """Map a feature namespace to its measured surface family."""
    if ns == "view":
        return "tui"
    return ns if ns in _SURFACES else "cli"


def imported_pack_note(header: Mapping[str, Any] | dict[str, Any]) -> str | None:
    """Return the merged-machines note, or None when nothing was imported."""

    if not isinstance(header, Mapping):
        return None
    try:
        count = int(header.get("imported_pack_count", 0) or 0)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    noun = "pack" if count == 1 else "packs"
    day = header.get("imported_day")
    if isinstance(day, str) and day:
        return f"+{count} imported {noun} (imported {day})"
    return f"+{count} imported {noun}"


def header_text(report: dict[str, Any]) -> Text:
    """Return the trust line for a report header."""
    header = dict(report.get("header", {}))
    actor = str(header.get("actor", "you"))
    window_days = header.get("window_days")
    window_label = "all" if window_days is None else f"{window_days}d"
    observed = header.get("observed_active_days", {})
    active = 0
    if isinstance(observed, dict):
        live = [int(observed.get(name, 0) or 0) for name in ("cli", "tui")]
        active = max(live) if live else 0
    window_total = window_days if isinstance(window_days, int) else active
    recording_since = header.get("recording_since") or "—"
    text = Text()
    text.append("FOOTPRINT", style="bold")
    text.append(f" · {actor}", style=MUTED_STYLE)
    text.append(f" · last {window_label}", style=MUTED_STYLE)
    text.append(f" · {active} of {window_total} days active", style=MUTED_STYLE)
    text.append(f" · recording since {recording_since}", style=MUTED_STYLE)
    note = imported_pack_note(header)
    if note is not None:
        text.append(f" · {note}", style=MUTED_STYLE)
    return text


def header_chip(report: dict[str, Any]) -> Text:
    """Return the readiness chip: PREVIEW (amber) or READY (accent)."""
    header = dict(report.get("header", {}))
    gate_met = bool(header.get("gate_met", False))
    if gate_met:
        return Text("READY", style=f"bold {RECENT_7D_STYLE}")
    active = int(header.get("gate_active_days", 0) or 0)
    required = int(header.get("gate_required_days", 30) or 0)
    return Text(
        f"PREVIEW {active}/{required} active days", style=f"bold {PREVIEW_STYLE}"
    )


def tiles_row(report: dict[str, Any], *, tile_width: int = 22) -> Group:
    """Return the five summary tiles for a report."""
    tiles = dict(report.get("tiles", {}))
    preview = bool(tiles.get("candidates_preview", False))
    candidates = int(tiles.get("candidates", 0) or 0)
    used = int(tiles.get("used", 0) or 0)
    total = int(tiles.get("total", 0) or 0)
    return Group(
        render_stat_tile(
            f"{format_count(used)} / {format_count(total)}",
            caption="Used",
            key="footprint-used",
            width=tile_width,
            height=5,
        ),
        render_stat_tile(
            format_count(candidates),
            caption="Candidates · preview" if preview else "Candidates",
            key="footprint-candidates",
            width=tile_width,
            height=5,
            status="warning" if preview else None,
        ),
        render_stat_tile(
            format_count(int(tiles.get("rare_by_design", 0) or 0)),
            caption="Rare by design",
            key="footprint-rare",
            width=tile_width,
            height=5,
        ),
        render_stat_tile(
            format_count(int(tiles.get("agent_only", 0) or 0)),
            caption="Agent-only",
            key="footprint-agent",
            width=tile_width,
            height=5,
        ),
        render_stat_tile(
            format_count(int(tiles.get("not_measured", 0) or 0)),
            caption="Not measured",
            key="footprint-unmeasured",
            width=tile_width,
            height=5,
        ),
    )


def area_row_text(area: dict[str, Any], *, strip_width: int = 24) -> Text:
    """Return one map-lens area row with a proportional heat strip."""
    label = str(area.get("area", ""))
    total = max(0, int(area.get("total", 0) or 0))
    used = max(0, int(area.get("used", 0) or 0))
    pct = int(area.get("used_pct", 0) or 0)
    text = Text()
    text.append(label.ljust(22)[:22], style="bold")
    text.append(" ")
    text.append_text(heat_strip(area, width=strip_width))
    text.append(f"  {used}/{total}  {pct}%", style=MUTED_STYLE)
    if total > 0 and used / total < 0.25:
        text.append(f"  {COLD_MARKER}", style=PREVIEW_STYLE)
    return text


def feature_row_text(row: dict[str, Any]) -> Text:
    """Return one feature row as a single line for list views."""
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
    last = row.get("last_used_day")
    if last:
        text.append(f"  last {last}", style=MUTED_STYLE)
    via = row.get("via", {})
    if isinstance(via, dict) and via:
        mix = " + ".join(f"{name} {count}" for name, count in sorted(via.items())[:3])
        text.append(f"  via {mix}", style=MUTED_STYLE)
    loc = row.get("loc")
    if isinstance(loc, int):
        text.append(f"  {format_count(loc)} LOC", style=MUTED_STYLE)
    badge = decision_badge_text(row)
    if badge is not None:
        text.append("  ")
        text.append_text(badge)
    incomplete = bool(row.get("coverage_incomplete", False))
    if incomplete:
        text.append("  incomplete", style=PREVIEW_STYLE)
    return text


def decision_badge_text(row: Mapping[str, Any] | dict[str, Any]) -> Text | None:
    """Return the decision badge for a row, or None when undecided."""
    decision = row.get("decision")
    if not isinstance(decision, str) or not decision:
        return None
    label, style = DECISION_BADGES.get(decision, (decision, MUTED_STYLE))
    reason = row.get("decision_reason")
    suffix = f":{reason}" if isinstance(reason, str) and reason else ""
    return Text(f"[{label}{suffix}]", style=style)


def card_panel(card: dict[str, Any], header: dict[str, Any]) -> Panel:
    """Return the evidence card panel for ``footprint show``."""
    row = dict(card.get("row", {}))
    label = str(row.get("label", row.get("id", "")))
    subtitle = f"{row.get('id', '')} · {row.get('area', '')} · {row.get('kind', '')}"
    lines: list[RenderableType] = []
    lines.append(Text(evidence_sentence(card, header), style=""))
    note = imported_pack_note(header)
    if note is not None:
        lines.append(Text(note, style=MUTED_STYLE))
    uses = row.get("uses", {})
    if isinstance(uses, dict):
        lines.append(
            Text(
                f"Uses  human {uses.get('human', 0)} · agent {uses.get('agent', 0)}"
                f" · automation {uses.get('automation', 0)}"
                f"     last: {row.get('last_used_day') or '—'}"
                f" ({row.get('last_used_actor') or '—'})",
                style=MUTED_STYLE,
            )
        )
    series = card.get("daily_series", [])
    if isinstance(series, list) and series:
        lines.append(Text(f"Activity  {activity_strip(series, width=52)}"))
    via = row.get("via", {})
    if isinstance(via, dict) and via:
        lines.append(
            Text(
                "Reached via  "
                + " · ".join(f"{name} {count}" for name, count in sorted(via.items())),
                style=MUTED_STYLE,
            )
        )
    siblings = list(card.get("retire_with", []) or [])
    protected = row.get("protected")
    loc = row.get("loc")
    carries = str(row.get("id", ""))
    if loc is not None:
        carries += f" · {format_count(loc)} LOC"
    if protected:
        carries += f" · protected:{protected}"
    lines.append(Text(f"Carries  {carries}", style=MUTED_STYLE))
    if siblings:
        lines.append(Text(f"Siblings  {', '.join(siblings)}", style=MUTED_STYLE))
    badge = decision_badge_text(row)
    decision_line = Text("Decision  ")
    if badge is not None:
        decision_line.append_text(badge)
    else:
        decision_line.append("○ undecided", style=MUTED_STYLE)
    lines.append(decision_line)
    title = Text(label, style="bold")
    return Panel(
        Group(*lines),
        title=title,
        subtitle=subtitle,
        subtitle_align="left",
        border_style="cyan",
        padding=(1, 2),
    )


def area_card_panel(summary: dict[str, Any], header: dict[str, Any]) -> Panel:
    """Return the area summary card for the map lens: totals, buckets, LOC."""
    area = str(summary.get("area", ""))
    ns = str(summary.get("ns", ""))
    total = max(0, int(summary.get("total", 0) or 0))
    used = max(0, int(summary.get("used", 0) or 0))
    pct = int(summary.get("used_pct", 0) or 0)
    lines: list[RenderableType] = [
        Text(f"{used}/{total} used · {pct}%", style="bold"),
        Text(
            "recency ≤7d "
            f"{int(summary.get('recency_7d', 0) or 0)}"
            " · ≤30d "
            f"{int(summary.get('recency_30d', 0) or 0)}"
            " · in window "
            f"{int(summary.get('recency_window', 0) or 0)}"
            " · no recorded use "
            f"{int(summary.get('recency_none', 0) or 0)}"
            " · not measured "
            f"{int(summary.get('recency_not_measured', 0) or 0)}",
            style=MUTED_STYLE,
        ),
    ]
    note = imported_pack_note(header)
    if note is not None:
        lines.append(Text(note, style=MUTED_STYLE))
    unused = summary.get("unused_by_loc", [])
    if isinstance(unused, list) and unused:
        lines.append(Text("Largest unused by LOC", style="bold"))
        for row in unused[:5]:
            if not isinstance(row, Mapping):
                continue
            label = str(row.get("label", row.get("id", "")))
            feature_id = str(row.get("id", ""))
            loc = row.get("loc")
            loc_text = f" · {format_count(loc)} LOC" if isinstance(loc, int) else ""
            lines.append(Text(f"{label} `{feature_id}`{loc_text}", style=MUTED_STYLE))
    else:
        lines.append(Text("No unused features in this area.", style=MUTED_STYLE))
    return Panel(
        Group(*lines),
        title=Text(area, style="bold"),
        subtitle=f"{ns} · area summary",
        subtitle_align="left",
        border_style="cyan",
        padding=(1, 2),
    )


def activity_strip(series: list[dict[str, Any]], *, width: int = 52) -> Text:
    """Render daily activity; unmeasured days are a dim gap, never a zero bar."""
    width = max(8, int(width))
    points = list(series)
    if len(points) > width:
        points = _bucket_max(points, width)
    text = Text()
    peak = max([max(0, int(item.get("n", 0) or 0)) for item in points] + [0])
    for item in points:
        if not bool(item.get("measured", False)):
            text.append("·", style=MUTED_STYLE)
            continue
        count = max(0, int(item.get("n", 0) or 0))
        if count <= 0:
            text.append("·", style=MUTED_STYLE)
            continue
        if peak <= 0:
            text.append(SPARK_BLOCKS[3])
            continue
        index = round(count / peak * (len(SPARK_BLOCKS) - 1))
        text.append(SPARK_BLOCKS[index])
    return text


def _bucket_max(points: list[dict[str, Any]], width: int) -> list[dict[str, Any]]:
    """Downsample a daily series to *width* buckets keeping the max count."""
    buckets: list[dict[str, Any]] = []
    size = len(points) / width
    for index in range(width):
        end = len(points) if index == width - 1 else int((index + 1) * size)
        chunk = points[int(index * size) : end]
        if not chunk:
            continue
        measured = any(bool(item.get("measured", False)) for item in chunk)
        peak = max(int(item.get("n", 0) or 0) for item in chunk)
        buckets.append(
            {"day": chunk[0].get("day", ""), "n": peak, "measured": measured}
        )
    return buckets


def evidence_sentence(card_or_row: dict[str, Any], header: dict[str, Any]) -> str:
    """Return plain-language evidence that always states its denominator."""
    row = dict(card_or_row.get("row", card_or_row))
    state = str(row.get("state", ""))
    feature_id = str(row.get("id", ""))
    ns = str(row.get("ns", ""))
    surface = surface_for_ns(ns)
    observed = _observed_days(header, surface)
    actor = str(header.get("actor", "you"))
    actor_phrase = _actor_phrase(actor)
    denominator = f"{observed} observed active day{'s' if observed != 1 else ''}"
    qualifier = (
        " Evidence is incomplete (gaps in coverage)."
        if bool(row.get("coverage_incomplete", False))
        else ""
    )
    decision_suffix = _decision_suffix(row)
    if state == "used":
        days = int(row.get("days_used", 0) or 0)
        last = row.get("last_used_day")
        last_phrase = f", last used {last}" if last else ""
        return (
            f"Used {actor_phrase} on {days} of {denominator}{last_phrase}."
            f"{qualifier}{decision_suffix}"
        )
    if state == "no_recorded_use":
        return (
            f"No recorded use {actor_phrase} across {denominator}."
            f"{qualifier}{decision_suffix}"
        )
    if state == "rare_by_design":
        protected = row.get("protected") or "rare by design"
        return (
            f"Rare by design ({protected}): excluded from candidates."
            f" No recorded use {actor_phrase} across {denominator}."
            f"{qualifier}{decision_suffix}"
        )
    if state == "too_new":
        since = _catalog_since(card_or_row, row)
        required = int(header.get("gate_required_days", 30) or 0)
        active = int(header.get("gate_active_days", 0) or 0)
        return (
            f"Too new for review ({feature_id} in catalog since {since}):"
            f" needs {required} active days ({active} so far)."
            f"{qualifier}{decision_suffix}"
        )
    if state == "not_measured":
        return (
            f"Not measured: the {surface} surface has no measured day"
            f" in the window, so {feature_id} cannot be a candidate."
            f"{decision_suffix}"
        )
    if state == "retired":
        return (
            f"Retired: {feature_id} is not in the latest catalog revision."
            f"{decision_suffix}"
        )
    return (
        f"No evidence for {feature_id} across {denominator}."
        f"{qualifier}{decision_suffix}"
    )


def _actor_phrase(actor: str) -> str:
    return {
        "you": "by you",
        "agents": "by agents",
        "automation": "by automation",
        "everyone": "by anyone",
    }.get(actor, f"by {actor}")


def _observed_days(header: dict[str, Any], surface: str) -> int:
    observed = header.get("observed_active_days", {})
    if isinstance(observed, dict):
        try:
            return max(0, int(observed.get(surface, 0) or 0))
        except (TypeError, ValueError):
            return 0
    return 0


def _catalog_since(card_or_row: dict[str, Any], row: dict[str, Any]) -> str:
    for key in ("first_in_catalog",):
        value = card_or_row.get(key, row.get(key))
        if isinstance(value, str) and value:
            return value
    return "recently"


def _decision_suffix(row: dict[str, Any]) -> str:
    decision = row.get("decision")
    if not isinstance(decision, str) or not decision:
        return ""
    reason = row.get("decision_reason")
    if isinstance(reason, str) and reason:
        return f" Decision: {decision} ({reason})."
    return f" Decision: {decision}."


def legend_text() -> Text:
    """Return the glyph key shared by list, card, and the TUI view."""
    text = Text(style=MUTED_STYLE)
    text.append("●", style="green")
    text.append(" used  ")
    text.append("○", style=NOT_MEASURED_GLYPH)
    text.append(" candidate  ")
    text.append("◈ ", style=MUTED_STYLE)
    text.append("rare by design  ")
    text.append("◐ ", style=PREVIEW_STYLE)
    text.append("too new  ")
    text.append(f"{NOT_MEASURED_GLYPH} ", style=NOT_MEASURED_GLYPH)
    text.append("not measured  ")
    text.append("· ", style=MUTED_STYLE)
    text.append("no recorded use  ")
    text.append("! ", style=FAULT_STYLE)
    text.append("collector fault")
    return text


__all__ = [
    "activity_strip",
    "area_card_panel",
    "area_row_text",
    "card_panel",
    "decision_badge_text",
    "evidence_sentence",
    "feature_row_text",
    "header_chip",
    "header_text",
    "imported_pack_note",
    "legend_text",
    "surface_for_ns",
    "tiles_row",
]

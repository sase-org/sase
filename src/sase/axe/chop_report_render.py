"""Literal Rich rendering for structured axe chop reports."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from rich.text import Text

TONE_STYLES: dict[str, str] = {
    "neutral": "#D7AF87",
    "muted": "dim #A8A8A8",
    "info": "#87D7FF",
    "ok": "#5FD75F",
    "warn": "#FFAF5F",
    "error": "#FF5F5F",
    "accent": "bold #FFD700",
}

_TONE_GLYPHS: dict[str, str] = {
    "neutral": "",
    "muted": "·",
    "info": "•",
    "ok": "✓",
    "warn": "◆",
    "error": "▲",
    "accent": "",
}
_NARROW_WIDTH = 60
_DEFAULT_WIDTH = 72
_ROW_GAP = 2
_GAUGE_CELLS = 16
_NUMERIC_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def render_section_rule(title: str, *, width: int | None = None) -> Text:
    """Render a copper section rule sized to the available panel width."""
    label = f"━━ {title} "
    target = width if width is not None and width > 0 else _DEFAULT_WIDTH
    return Text(label + "─" * max(2, target - len(label)), style=TONE_STYLES["neutral"])


def render_chop_report(report: Mapping[str, Any], *, width: int | None = None) -> Text:
    """Render one validated report document without parsing markup or ANSI."""
    text = Text()
    title = report.get("title")
    if isinstance(title, str) and title:
        text.append_text(render_section_rule(title, width=width))
        text.append("\n")

    blocks = _as_sequence(report.get("blocks"))
    if blocks is None:
        return text
    narrow = width is not None and 0 < width < _NARROW_WIDTH
    for raw_block in blocks:
        if not isinstance(raw_block, Mapping):
            continue
        rendered = _render_block(raw_block, width=width, narrow=narrow)
        if rendered is None:
            continue
        text.append_text(rendered)
    if text.plain.endswith("\n"):
        text.rstrip()
    return text


def _render_block(
    block: Mapping[str, Any], *, width: int | None, narrow: bool
) -> Text | None:
    kind = block.get("kind")
    if kind == "headline":
        return _render_toned_line(block, bold=True)
    if kind == "heading":
        value = block.get("text")
        if not isinstance(value, str):
            return None
        return Text(f"  {value}\n", style=f"bold {TONE_STYLES['info']}")
    if kind == "text":
        return _render_toned_line(block)
    if kind == "kv":
        return _render_kv(block, narrow=narrow)
    if kind == "rows":
        return _render_rows(block, width=width, narrow=narrow)
    if kind == "bullets":
        return _render_bullets(block)
    if kind == "gauge":
        return _render_gauge(block)
    if kind == "divider":
        target = width if width is not None and width > 0 else _DEFAULT_WIDTH
        return Text(
            "  " + "─" * max(2, target - 4) + "\n",
            style=TONE_STYLES["muted"],
        )
    return None


def _render_toned_line(block: Mapping[str, Any], *, bold: bool = False) -> Text | None:
    value = block.get("text")
    tone = _tone(block.get("tone"))
    if not isinstance(value, str) or tone is None:
        return None
    style = TONE_STYLES[tone]
    if bold:
        style = f"bold {style}"
    glyph = _TONE_GLYPHS[tone]
    prefix = f"{glyph} " if glyph else ""
    return Text(f"  {prefix}{value}\n", style=style)


def _render_kv(block: Mapping[str, Any], *, narrow: bool) -> Text | None:
    items = _as_sequence(block.get("items"))
    if items is None:
        return None
    rendered = Text()
    first = True
    for item in items:
        if not isinstance(item, Mapping):
            continue
        key = item.get("key")
        value = item.get("value")
        tone = _tone(item.get("tone"))
        if not isinstance(key, str) or not isinstance(value, str) or tone is None:
            continue
        if narrow or first:
            rendered.append("  ")
        else:
            rendered.append("    ")
        rendered.append(f"{key} ", style=f"bold {TONE_STYLES['info']}")
        rendered.append(value, style=TONE_STYLES[tone])
        if narrow:
            rendered.append("\n")
        first = False
    if not rendered:
        return None
    if not narrow:
        rendered.append("\n")
    return rendered


def _render_rows(
    block: Mapping[str, Any], *, width: int | None, narrow: bool
) -> Text | None:
    raw_rows = _as_sequence(block.get("rows"))
    if raw_rows is None:
        return None
    columns = _string_sequence(block.get("columns"))
    rows: list[tuple[list[str], str, str]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            continue
        cells = _string_sequence(raw_row.get("cells"))
        tone = _tone(raw_row.get("tone"))
        if not cells or tone is None:
            continue
        raw_glyph = raw_row.get("glyph")
        glyph = raw_glyph if isinstance(raw_glyph, str) else _TONE_GLYPHS[tone]
        rows.append((cells, tone, glyph))
    if not rows:
        return None
    if narrow:
        return _render_narrow_rows(columns, rows)
    return _render_wide_rows(columns, rows, width=width)


def _render_narrow_rows(
    columns: list[str] | None, rows: list[tuple[list[str], str, str]]
) -> Text:
    rendered = Text()
    for cells, tone, glyph in rows:
        prefix = f"{glyph} " if glyph else ""
        rendered.append(f"  {prefix}{cells[0]}\n", style=TONE_STYLES[tone])
        details: list[tuple[str, str]] = []
        for index, value in enumerate(cells[1:], start=1):
            label = (
                columns[index] if columns and index < len(columns) else str(index + 1)
            )
            details.append((label, value))
        if details:
            rendered.append("    ")
            for index, (label, value) in enumerate(details):
                if index:
                    rendered.append("  ·  ", style="dim")
                rendered.append(f"{label}: ", style=f"bold {TONE_STYLES['info']}")
                rendered.append(value, style=TONE_STYLES[tone])
            rendered.append("\n")
    return rendered


def _render_wide_rows(
    columns: list[str] | None,
    rows: list[tuple[list[str], str, str]],
    *,
    width: int | None,
) -> Text:
    count = max(len(cells) for cells, _, _ in rows)
    values_by_column = [
        [cells[index] for cells, _, _ in rows if index < len(cells)]
        for index in range(count)
    ]
    widths = [
        max(
            [len(value) for value in values]
            + ([len(columns[index])] if columns and index < len(columns) else [1])
        )
        for index, values in enumerate(values_by_column)
    ]
    target = width if width is not None and width > 0 else _DEFAULT_WIDTH
    available = max(count, target - 6 - _ROW_GAP * (count - 1))
    while sum(widths) > available and max(widths) > 1:
        widest = max(range(count), key=widths.__getitem__)
        widths[widest] -= 1
    numeric = [
        bool(values) and all(_NUMERIC_RE.fullmatch(value.strip()) for value in values)
        for values in values_by_column
    ]

    rendered = Text()
    if columns:
        rendered.append("    ")
        _append_cells(
            rendered,
            columns,
            widths,
            numeric,
            style=f"bold {TONE_STYLES['info']}",
        )
        rendered.append("\n")
    for cells, tone, glyph in rows:
        rendered.append("  ")
        rendered.append(f"{glyph} " if glyph else "  ", style=TONE_STYLES[tone])
        _append_cells(rendered, cells, widths, numeric, style=TONE_STYLES[tone])
        rendered.append("\n")
    return rendered


def _append_cells(
    rendered: Text,
    cells: list[str],
    widths: list[int],
    numeric: list[bool],
    *,
    style: str,
) -> None:
    for index, cell_width in enumerate(widths):
        if index:
            rendered.append(" " * _ROW_GAP)
        value = cells[index] if index < len(cells) else ""
        elided = _elide_cell(value, cell_width)
        aligned = (
            elided.rjust(cell_width) if numeric[index] else elided.ljust(cell_width)
        )
        rendered.append(aligned, style=style)


def _elide_cell(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 1:
        return "…"
    if "/" in value and width >= 3:
        return "…/" + value[-(width - 2) :].lstrip("/")
    return value[: width - 1] + "…"


def _render_bullets(block: Mapping[str, Any]) -> Text | None:
    items = _as_sequence(block.get("items"))
    if items is None:
        return None
    rendered = Text()
    for item in items:
        if not isinstance(item, Mapping):
            continue
        value = item.get("text")
        tone = _tone(item.get("tone"))
        if not isinstance(value, str) or tone is None:
            continue
        raw_glyph = item.get("glyph")
        glyph = raw_glyph if isinstance(raw_glyph, str) else _TONE_GLYPHS[tone]
        rendered.append(f"  {glyph or '•'} {value}\n", style=TONE_STYLES[tone])
    return rendered or None


def _render_gauge(block: Mapping[str, Any]) -> Text | None:
    label = block.get("label")
    value = block.get("value")
    maximum = block.get("max")
    tone = _tone(block.get("tone"))
    if (
        not isinstance(label, str)
        or not isinstance(value, int)
        or not isinstance(maximum, int)
        or maximum <= 0
        or tone is None
    ):
        return None
    filled = round(_GAUGE_CELLS * min(max(value, 0), maximum) / maximum)
    bar = "█" * filled + "░" * (_GAUGE_CELLS - filled)
    rendered = Text("  ")
    rendered.append(f"{label} ", style=f"bold {TONE_STYLES['info']}")
    rendered.append(bar, style=TONE_STYLES[tone])
    rendered.append(f" {value}/{maximum}\n", style=TONE_STYLES[tone])
    return rendered


def _tone(value: object) -> str | None:
    tone = "neutral" if value is None else value
    return tone if isinstance(tone, str) and tone in TONE_STYLES else None


def _as_sequence(value: object) -> Sequence[Any] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return None


def _string_sequence(value: object) -> list[str] | None:
    sequence = _as_sequence(value)
    if sequence is None:
        return None
    strings = list(sequence)
    return strings if all(isinstance(item, str) for item in strings) else None


__all__ = ["TONE_STYLES", "render_chop_report", "render_section_rule"]

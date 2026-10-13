"""Rich rendering for Archive list items, the Inbox pulse, and banners.

Rows are built only from core light-row fields (time basis and runtime come
from the corpus, never from file mtimes). The Archive's chrome is amber; done
and failed outcomes are dim green and dim red; an interrupted run keeps the
existing STOPPED violet as ``○ WAS <stored status>``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import tzinfo
from typing import Any

from rich.cells import cell_len
from rich.text import Text
from sase.core.time import get_timezone

from ...agent_count_chip import format_agent_count_chip
from ...command_line.context import middle_truncate
from ...models._agent_time_wait import format_compact_duration
from ...models.agent_archive_controller import ArchiveInboxPulse
from ...models.agent_archive_list import (
    ITEM_BANNER,
    ITEM_CONTAINER,
    ITEM_LOADING,
    ITEM_MEMBER,
    ITEM_MESSAGE,
    ITEM_ROW,
    ITEM_TAIL,
    ArchiveListItem,
    parse_archive_timestamp,
)
from ...models.agent_status import STOPPED_COLOR
from .._agent_list_helpers import short_model_name

ARCHIVE_CHROME_STYLE = "#d7af5f"
_DONE_STYLE = "dim #5faf5f"
_FAILED_STYLE = "dim #d75f5f"
_INTERRUPTED_STYLE = f"bold {STOPPED_COLOR}"
_DIM = "dim"
_MIN_NAME_WIDTH = 16
_GAP = 2
_MEMBER_INDENT = "    "
_ROW_INDENT = "  "
_MAX_OUTCOME_WIDTH = 22


@dataclass(frozen=True)
class ArchiveRenderContext:
    """Per-render inputs shared by every row."""

    tz: tzinfo | None = None
    grouping: str = "day"
    width: int = 56
    outcome_width: int = 0
    restored_keys: frozenset[str] = frozenset()
    marked_keys: frozenset[str] = frozenset()


def _outcome_label(row: Mapping[str, Any]) -> tuple[str, str]:
    """Return the past-tense outcome text and style for a light row."""
    outcome = str(row.get("outcome") or "")
    if outcome == "done":
        return "✓ done", _DONE_STYLE
    if outcome == "failed":
        return "✗ failed", _FAILED_STYLE
    status = str(row.get("status") or "").strip() or "UNKNOWN"
    return f"○ WAS {status}", _INTERRUPTED_STYLE


def outcome_cell_width(items: Sequence[ArchiveListItem]) -> int:
    """Return the widest outcome chip among run rows, capped for alignment."""
    widest = 0
    for item in items:
        if item.row is not None and item.kind in {
            ITEM_ROW,
            ITEM_CONTAINER,
            ITEM_MEMBER,
        }:
            widest = max(widest, cell_len(_outcome_label(item.row)[0]))
    return min(widest, _MAX_OUTCOME_WIDTH)


def _time_width(ctx: ArchiveRenderContext) -> int:
    return 5 if ctx.grouping == "day" else 12


def _time_chip(row: Mapping[str, Any], ctx: ArchiveRenderContext) -> Text:
    """Render the core-derived time; a start-only time is dim italic."""
    moment = parse_archive_timestamp(
        row.get("last_activity_at"), ctx.tz or get_timezone()
    )
    if moment is None:
        return Text("--", style=_DIM)
    if ctx.grouping == "day":
        text = f"{moment:%H:%M}"
    else:
        text = f"{moment:%b} {moment.day} {moment:%H:%M}"
    basis = str(row.get("time_basis") or "")
    if basis == "started":
        return Text(text, style="dim italic")
    if basis == "dismissed":
        return Text(text, style=_DIM)
    return Text(text)


def _name_for(item: ArchiveListItem) -> str:
    row = item.row or {}
    for key in ("agent_name", "name", "cl_name"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    archive_key = row.get("archive_key")
    if isinstance(archive_key, Mapping):
        run_id = archive_key.get("source_run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    return "(unnamed)"


def _suffix_parts(item: ArchiveListItem) -> dict[str, tuple[str, str]]:
    """Return the right-hand chips keyed by drop-order name."""
    row = item.row or {}
    parts: dict[str, tuple[str, str]] = {}
    if item.kind == ITEM_CONTAINER and item.count:
        parts["count"] = (f"×{item.count}", f"bold {ARCHIVE_CHROME_STYLE}")
    model = row.get("model")
    if isinstance(model, str) and model:
        parts["model"] = (short_model_name(model), "dim #8787af")
    runtime = row.get("runtime_seconds")
    if isinstance(runtime, int | float) and not isinstance(runtime, bool):
        parts["runtime"] = (format_compact_duration(float(runtime)), _DIM)
    if row.get("restorable") is False:
        parts["exception"] = ("⊘ no restore", "dim #af5f5f")
    return parts


def _suffix_width(parts: Mapping[str, tuple[str, str]]) -> int:
    if not parts:
        return 0
    return (
        _GAP + sum(cell_len(text) for text, _style in parts.values()) + len(parts) - 1
    )


def _format_run(item: ArchiveListItem, ctx: ArchiveRenderContext) -> Text:
    """Render a run, container, or member row from its core light row.

    Names are middle-truncated. When width is short MODEL and then RUNTIME
    drop out before the exception chip; a container's size chip never drops.
    """
    row = item.row or {}
    indent = _MEMBER_INDENT if item.kind == ITEM_MEMBER else _ROW_INDENT
    mark = "[✓] " if item.key in ctx.marked_keys else ""
    time_text = _time_chip(row, ctx)
    outcome_text, outcome_style = _outcome_label(row)
    outcome = Text(outcome_text, style=outcome_style)
    glyph = ""
    if item.kind == ITEM_CONTAINER:
        glyph = "▾ " if item.expanded else "▸ "
    fixed = (
        len(indent)
        + cell_len(mark)
        + _time_width(ctx)
        + _GAP
        + max(ctx.outcome_width, outcome.cell_len)
        + _GAP
        + cell_len(glyph)
    )
    parts = _suffix_parts(item)
    is_restored = item.key in ctx.restored_keys
    restored = " ⌂ restored" if is_restored else ""
    restored_width = cell_len(restored)
    for dropped in ("model", "runtime", "exception"):
        if ctx.width - fixed - _suffix_width(parts) - restored_width >= _MIN_NAME_WIDTH:
            break
        parts.pop(dropped, None)
    name = middle_truncate(
        _name_for(item),
        max(6, ctx.width - fixed - _suffix_width(parts) - restored_width),
    )

    line = Text(indent)
    if mark:
        line.append(mark, style="bold #00D700")
    line.append_text(time_text)
    line.append(" " * (_time_width(ctx) - time_text.cell_len + _GAP))
    line.append_text(outcome)
    line.append(" " * (max(0, ctx.outcome_width - outcome.cell_len) + _GAP))
    if glyph:
        line.append(glyph, style=ARCHIVE_CHROME_STYLE)
    if item.kind == ITEM_CONTAINER:
        name_style = "bold dim" if is_restored else "bold"
    else:
        name_style = "dim" if is_restored else ""
    line.append(name, style=name_style)
    if restored:
        line.append(restored, style=ARCHIVE_CHROME_STYLE)
    if parts:
        suffix = Text()
        for index, (text, style) in enumerate(parts.values()):
            if index:
                suffix.append(" ")
            suffix.append(text, style=style)
        line.append(" " * max(_GAP, ctx.width - line.cell_len - suffix.cell_len))
        line.append_text(suffix)
    return line


def _format_banner(item: ArchiveListItem) -> Text:
    """Render a date/group banner: fold glyph, amber label, run count."""
    line = Text()
    line.append("▾ " if item.open else "▸ ", style=ARCHIVE_CHROME_STYLE)
    line.append(item.label, style=f"bold {ARCHIVE_CHROME_STYLE}")
    noun = "run" if item.count == 1 else "runs"
    line.append(f"  {item.count} {noun}", style=_DIM)
    return line


def _format_tail(item: ArchiveListItem) -> Text:
    """Render the selectable ``⋮ N more · l`` page tail."""
    line = Text(_ROW_INDENT)
    line.append(f"⋮ {item.remaining} more · l", style=f"italic {ARCHIVE_CHROME_STYLE}")
    return line


def _format_note(item: ArchiveListItem) -> Text:
    """Render a non-selectable loading or status row."""
    style = "dim italic"
    if item.kind == ITEM_MESSAGE and "unavailable" in item.label:
        style = "italic #d75f5f"
    return Text(
        ("" if item.kind == ITEM_MESSAGE else _ROW_INDENT) + item.label, style=style
    )


def format_archive_item(item: ArchiveListItem, ctx: ArchiveRenderContext) -> Text:
    """Render any Archive list item."""
    if item.kind == ITEM_BANNER:
        return _format_banner(item)
    if item.kind == ITEM_TAIL:
        return _format_tail(item)
    if item.kind in {ITEM_LOADING, ITEM_MESSAGE}:
        return _format_note(item)
    return _format_run(item, ctx)


def format_pulse(pulse: ArchiveInboxPulse, *, selected: bool = False) -> Text:
    """Render ``⌂ Inbox · N [R… W… U…] · M needs you`` (attention omitted at 0)."""
    line = Text()
    line.append("⌂ Inbox", style="bold " + ("reverse " if selected else "") + "#AFAFAF")
    line.append(f" · {pulse.total}", style="bold #FFFFFF")
    chip = format_agent_count_chip(
        running=pulse.running, waiting=pulse.waiting, unread=pulse.unread
    )
    if chip.cell_len:
        line.append(" ")
        line.append_text(chip)
    if pulse.attention > 0:
        line.append(" · ", style=_DIM)
        line.append(f"{pulse.attention} needs you", style="bold #FFAF00")
    return line


__all__ = [
    "ARCHIVE_CHROME_STYLE",
    "ArchiveRenderContext",
    "format_archive_item",
    "format_pulse",
    "outcome_cell_width",
]

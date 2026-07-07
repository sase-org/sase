"""Timeline renderers for the tools panel."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.tools import SlowToolSource, ToolCallEntry
from sase.ace.tui.tools._constants import SLOW_TOOL_CALL_THRESHOLD_MS
from sase.ace.tui.tools.slow import format_long_duration

from ._tools_panel_details import append_expanded_block, expanded_markdown_lines
from ._tools_panel_time import format_timestamp
from ._tools_panel_types import (
    ToolDetailLevel,
    ToolTimelineRow,
    coerce_detail_level,
    detail_level_label,
)
from .prompt_panel._agent_context_common import truncate_display

_CHIP_COLORS = (
    "#87D7FF",
    "#5FD75F",
    "#D7AF5F",
    "#AF87FF",
    "#5FD7D7",
    "#D787AF",
)
_SOURCE_CHIP_WIDTH = 7


def format_duration(duration_ms: int | None) -> str:
    if duration_ms is None:
        return ""
    if duration_ms >= SLOW_TOOL_CALL_THRESHOLD_MS:
        return format_long_duration(duration_ms)
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    seconds = duration_ms / 1000
    if seconds < 10:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


def status_label(status: str) -> str:
    return {
        "success": "ok",
        "failure": "fail",
        "interrupted": "stop",
        "subagent": "agent",
        "pending": "wait",
        "incomplete": "miss",
    }.get(status, status or "unknown")


def status_style(status: str) -> str:
    return {
        "success": "bold green",
        "failure": "bold red",
        "interrupted": "bold yellow",
        "subagent": "bold #87D7FF",
        "pending": "bold #FFD787",
        "incomplete": "dim #FFD787",
    }.get(status, "dim")


def _append_bounded(
    text: Text, value: str, *, style: str = "", limit: int = 96
) -> None:
    value = " ".join(value.split())
    if len(value) > limit:
        value = value[: limit - 1] + "..."
    text.append(value, style=style)


def _pad_cells(value: str, width: int) -> str:
    return value + (" " * max(0, width - cell_len(value)))


def _append_source_chip(
    text: Text,
    label: str,
    *,
    palette_index: int,
) -> None:
    chip = _pad_cells(truncate_display(label, _SOURCE_CHIP_WIDTH), _SOURCE_CHIP_WIDTH)
    text.append(
        chip,
        style=f"italic {_CHIP_COLORS[palette_index % len(_CHIP_COLORS)]}",
    )


def rows_from_entries(
    entries: Sequence[ToolCallEntry] | None,
) -> tuple[ToolTimelineRow, ...] | None:
    if entries is None:
        return None
    return tuple(ToolTimelineRow(entry=entry) for entry in entries)


def rows_from_sources(
    sources: tuple[SlowToolSource, ...] | None,
) -> tuple[ToolTimelineRow, ...] | None:
    if sources is None:
        return None
    rows = tuple(
        ToolTimelineRow(
            entry=entry,
            source_label=source.label,
            palette_index=source.palette_index,
        )
        for source in sources
        for entry in source.entries
    )
    return tuple(sorted(rows, key=_timeline_row_sort_key))


def _timeline_row_sort_key(row: ToolTimelineRow) -> tuple[object, ...]:
    entry = row.entry
    return (
        entry._recorded_at_sort,
        entry._file_order,
        entry.line_number,
        entry.tool_use_id or "",
        row.palette_index,
    )


def build_tools_timeline_text(
    entries: Sequence[ToolCallEntry] | None,
    fetch_time: datetime,
    *,
    is_stale: bool = False,
    rows: Sequence[ToolTimelineRow] | None = None,
    detail_level: ToolDetailLevel | int = ToolDetailLevel.COMPACT,
) -> Text:
    """Build the Rich Text timeline for tool-call entries."""
    detail_level = coerce_detail_level(detail_level)
    if entries is None:
        return Text("No tools artifact available", style="dim italic")
    if not entries:
        return Text("No tool calls recorded", style="dim italic")

    failures = sum(1 for entry in entries if entry.status == "failure")
    interrupted = sum(1 for entry in entries if entry.status == "interrupted")
    output = Text()
    output.append("TOOLS", style="bold #87D7FF underline")
    if is_stale:
        output.append(" (refreshing...)", style="dim italic")
    output.append("\n")
    summary = (
        f"{len(entries)} calls · {failures} failures · {interrupted} interrupted "
        f"· refreshed {fetch_time.strftime('%H:%M:%S')}"
    )
    if detail_level >= ToolDetailLevel.EXPANDED:
        summary = f"{summary} · detail: {detail_level_label(detail_level)}"
    output.append(f"{summary}\n\n", style="dim")

    timeline_rows = tuple(rows) if rows is not None else rows_from_entries(entries)
    for row in timeline_rows or ():
        entry = row.entry
        output.append(format_timestamp(entry.recorded_at), style="dim")
        output.append("  ")
        output.append(
            status_label(entry.status).ljust(5), style=status_style(entry.status)
        )
        output.append("  ")
        if row.source_label:
            _append_source_chip(
                output,
                row.source_label,
                palette_index=row.palette_index,
            )
            output.append("  ")
        _append_bounded(output, entry.display_tool_name, style="bold")

        target = entry.compact_target
        if target:
            output.append("  ")
            _append_bounded(output, target, style="#D7D7AF", limit=88)

        duration = format_duration(entry.duration_ms)
        if duration:
            output.append("  ")
            style = (
                "bold #FFAF5F"
                if entry.duration_ms is not None
                and entry.duration_ms >= SLOW_TOOL_CALL_THRESHOLD_MS
                else "dim"
            )
            output.append(duration, style=style)

        detail = entry.detail
        if detail:
            output.append("\n    ")
            _append_bounded(output, detail, style="dim", limit=140)
        output.append("\n")
        if detail_level >= ToolDetailLevel.EXPANDED:
            append_expanded_block(output, entry, detail_level=detail_level)
            output.append("\n")

    return output


def build_tools_timeline_markdown(
    entries: Sequence[ToolCallEntry] | None,
    fetch_time: datetime,
    *,
    rows: Sequence[ToolTimelineRow] | None = None,
    detail_level: ToolDetailLevel | int = ToolDetailLevel.COMPACT,
) -> str | None:
    """Build a plain markdown rendering for editor/export actions."""
    detail_level = coerce_detail_level(detail_level)
    if entries is None:
        return "TOOLS\n\nNo tools artifact available.\n"
    if not entries:
        return "TOOLS\n\nNo tool calls recorded.\n"

    summary = f"{len(entries)} calls · refreshed {fetch_time.strftime('%H:%M:%S')}"
    if detail_level >= ToolDetailLevel.EXPANDED:
        summary = f"{summary} · detail: {detail_level_label(detail_level)}"
    lines = [
        "TOOLS",
        "",
        summary,
        "",
    ]
    timeline_rows = tuple(rows) if rows is not None else rows_from_entries(entries)
    for row in timeline_rows or ():
        entry = row.entry
        pieces = [
            format_timestamp(entry.recorded_at),
            status_label(entry.status),
        ]
        if row.source_label:
            pieces.append(row.source_label)
        pieces.append(entry.display_tool_name)
        if entry.compact_target:
            pieces.append(entry.compact_target)
        if format_duration(entry.duration_ms):
            pieces.append(format_duration(entry.duration_ms))
        lines.append(" | ".join(pieces))
        if entry.detail:
            lines.append(f"  {entry.detail}")
        if detail_level >= ToolDetailLevel.EXPANDED:
            lines.extend(expanded_markdown_lines(entry, detail_level=detail_level))
            lines.append("")
    lines.append("")
    return "\n".join(lines)

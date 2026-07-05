"""SLOW TOOL CALLS section rendering for the prompt panel header."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.tools import SlowToolSource
from sase.ace.tui.tools._constants import (
    MAX_VISIBLE_SLOW_TOOL_CALLS,
    SLOW_TOOL_CALL_THRESHOLD_MS,
)
from sase.ace.tui.tools.slow import (
    SlowToolCall,
    format_long_duration,
    select_slow_tool_calls,
)

from ._agent_context_common import (
    COLOR_SUMMARY,
    COLOR_TIMESTAMP,
    COLOR_TRUNCATION,
    count_phrase,
    format_local_hhmmss,
    truncate_display,
)

_COLOR_HEADER = "bold #D7AF5F underline"
_COLOR_TOOL_NAME = "bold"
_COLOR_TARGET = "#D7D7AF"
_COLOR_COMPLETED_DURATION = "bold #FFAF5F"
_COLOR_RUNNING = "bold #FFD787"
_COLOR_DID_NOT_COMPLETE = "dim #FFD787"
_CHIP_COLORS = (
    "#87D7FF",
    "#5FD75F",
    "#D7AF5F",
    "#AF87FF",
    "#5FD7D7",
    "#D787AF",
)
_MAJOR_SECTION_RULE = "\u2500" * 50

_TOOL_NAME_WIDTH = 12
_TARGET_WIDTH = 44
_LABELED_TARGET_WIDTH = 35
_SOURCE_CHIP_WIDTH = 7
_DURATION_WIDTH = 7


@dataclass(frozen=True)
class _SourcedSlowToolCall:
    slow_call: SlowToolCall
    source: SlowToolSource


def append_slow_tool_calls_section(
    text: Text,
    *,
    sources: tuple[SlowToolSource, ...] | None,
    agent: object,
    now: datetime,
) -> None:
    """Append the SLOW TOOL CALLS section when any calls qualify."""
    del agent
    if not sources:
        return

    slow_calls = _select_sourced_slow_tool_calls(sources, now=now)
    if not slow_calls:
        return

    labeled = any(item.source.label for item in slow_calls)
    running_count = sum(1 for item in slow_calls if item.slow_call.is_running)
    summary_parts = [
        f"\u2265{format_long_duration(SLOW_TOOL_CALL_THRESHOLD_MS)}",
        count_phrase(len(slow_calls), "call"),
    ]
    if running_count:
        summary_parts.append(f"{running_count} running")
    if labeled:
        source_count = len({item.source.palette_index for item in slow_calls})
        summary_parts.append(count_phrase(source_count, "agent"))

    _append_major_section_divider(text)
    text.append("SLOW TOOL CALLS", style=_COLOR_HEADER)
    text.append(f" \u00b7 {' · '.join(summary_parts)}\n", style=COLOR_SUMMARY)
    text.append("\n")

    visible = slow_calls[:MAX_VISIBLE_SLOW_TOOL_CALLS]
    for item in visible:
        _append_slow_tool_call_row(text, item, labeled=labeled)

    overflow = len(slow_calls) - len(visible)
    if overflow > 0:
        text.append(
            f"  + {overflow} more \u00b7 press ] for the full tools timeline\n",
            style=COLOR_TRUNCATION,
        )


def _append_major_section_divider(text: Text) -> None:
    text.append("\n")
    text.append(_MAJOR_SECTION_RULE + "\n", style="dim")
    text.append("\n")


def _select_sourced_slow_tool_calls(
    sources: tuple[SlowToolSource, ...],
    *,
    now: datetime,
) -> tuple[_SourcedSlowToolCall, ...]:
    selected: list[_SourcedSlowToolCall] = []
    for source in sources:
        for slow_call in select_slow_tool_calls(
            source.entries,
            now=now,
            agent_is_active=source.agent_is_active,
            agent_end_reference=source.end_reference,
        ):
            selected.append(_SourcedSlowToolCall(slow_call=slow_call, source=source))
    selected.sort(
        key=lambda item: (
            not item.slow_call.is_running,
            -item.slow_call.effective_duration_ms,
        )
    )
    return tuple(selected)


def _append_slow_tool_call_row(
    text: Text,
    sourced: _SourcedSlowToolCall,
    *,
    labeled: bool,
) -> None:
    slow_call = sourced.slow_call
    entry = slow_call.entry
    glyph, glyph_style = _status_glyph_and_style(slow_call)
    target_width = _LABELED_TARGET_WIDTH if labeled else _TARGET_WIDTH
    tool_name = _pad_cells(
        truncate_display(entry.display_tool_name, _TOOL_NAME_WIDTH),
        _TOOL_NAME_WIDTH,
    )
    target = _pad_cells(
        truncate_display(entry.compact_target, target_width), target_width
    )
    duration = _left_pad_cells(
        format_long_duration(slow_call.effective_duration_ms),
        _DURATION_WIDTH,
    )

    text.append(f"  {format_local_hhmmss(entry.recorded_at)}  ", style=COLOR_TIMESTAMP)
    text.append(glyph, style=glyph_style)
    text.append(" ")
    if labeled:
        _append_source_chip(text, sourced.source)
        text.append(" ")
    text.append(tool_name, style=_COLOR_TOOL_NAME)
    text.append("  ")
    text.append(target, style=_COLOR_TARGET)
    text.append("  ")
    if slow_call.is_running:
        text.append(duration, style=_COLOR_RUNNING)
        text.append(" \u25cf running", style=_COLOR_RUNNING)
    elif slow_call.did_not_complete:
        text.append(duration, style=_COLOR_COMPLETED_DURATION)
        text.append(" did not complete", style=_COLOR_DID_NOT_COMPLETE)
    else:
        text.append(duration, style=_COLOR_COMPLETED_DURATION)
    text.append("\n")


def _append_source_chip(text: Text, source: SlowToolSource) -> None:
    label = truncate_display(source.label or "agent", _SOURCE_CHIP_WIDTH)
    text.append(
        _pad_cells(label, _SOURCE_CHIP_WIDTH),
        style=f"italic {_CHIP_COLORS[source.palette_index % len(_CHIP_COLORS)]}",
    )


def _status_glyph_and_style(slow_call: SlowToolCall) -> tuple[str, str]:
    if slow_call.is_running:
        return "\u23f3", _COLOR_RUNNING
    if slow_call.did_not_complete or slow_call.entry.status == "interrupted":
        return "\u25fc", "bold yellow"
    if slow_call.entry.status == "failure":
        return "\u2718", "bold red"
    if slow_call.entry.status == "success":
        return "\u2714", "bold green"
    return "\u25fc", "bold yellow"


def _pad_cells(value: str, width: int) -> str:
    return value + (" " * max(0, width - cell_len(value)))


def _left_pad_cells(value: str, width: int) -> str:
    return (" " * max(0, width - cell_len(value))) + value


__all__ = ["append_slow_tool_calls_section"]

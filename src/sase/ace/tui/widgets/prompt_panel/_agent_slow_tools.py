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
    normalize_slow_tool_call_threshold_ms,
    select_slow_tool_calls,
)
from sase.ace.tui.tools.report import (
    SlowToolCallReportSpec,
    tool_call_report_path,
)

from ._agent_context_common import (
    COLOR_SUMMARY,
    COLOR_TIMESTAMP,
    COLOR_TRUNCATION,
    count_phrase,
    format_local_hhmmss,
    truncate_display,
)
from ._agent_display_state import HeaderHintState
from ._helpers import append_major_section_divider, append_section_heading

_COLOR_HEADER = "bold #D7AF5F underline"
_COLOR_TOOL_NAME = "bold"
_COLOR_TARGET = "#D7D7AF"
_COLOR_COMPLETED_DURATION = "bold #FFAF5F"
_COLOR_RUNNING = "bold #FFD787"
_COLOR_DID_NOT_COMPLETE = "dim #FFD787"
_COLOR_HINT = "bold #FFFF00"
_CHIP_COLORS = (
    "#87D7FF",
    "#5FD75F",
    "#D7AF5F",
    "#AF87FF",
    "#5FD7D7",
    "#D787AF",
)
_TOOL_NAME_WIDTH = 12
_TARGET_WIDTH = 44
_LABELED_TARGET_WIDTH = 35
_SOURCE_CHIP_WIDTH = 7
_DURATION_WIDTH = 7


@dataclass(frozen=True)
class _SourcedSlowToolCall:
    slow_call: SlowToolCall
    source: SlowToolSource
    source_index: int


def append_slow_tool_calls_section(
    text: Text,
    *,
    sources: tuple[SlowToolSource, ...] | None,
    agent: object,
    now: datetime,
    hint_state: HeaderHintState | None = None,
    threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
) -> None:
    """Append the SLOW TOOL CALLS section when any calls qualify."""
    if not sources:
        return

    threshold_ms = normalize_slow_tool_call_threshold_ms(threshold_ms)
    slow_calls = _select_sourced_slow_tool_calls(
        sources, now=now, threshold_ms=threshold_ms
    )
    if not slow_calls:
        return

    labeled = any(item.source.label for item in slow_calls)
    running_count = sum(1 for item in slow_calls if item.slow_call.is_running)
    summary_parts = [
        f"\u2265{format_long_duration(threshold_ms)}",
        count_phrase(len(slow_calls), "call"),
    ]
    if running_count:
        summary_parts.append(f"{running_count} running")
    if labeled:
        source_count = len({item.source.palette_index for item in slow_calls})
        summary_parts.append(count_phrase(source_count, "agent"))

    append_major_section_divider(text)
    heading = Text("SLOW TOOL CALLS", style=_COLOR_HEADER)
    heading.append(f" \u00b7 {' · '.join(summary_parts)}", style=COLOR_SUMMARY)
    append_section_heading(text, heading)

    visible = _select_visible_slow_tool_calls(slow_calls)
    hint_marker_width = _hint_marker_width(visible, hint_state)
    agent_name = _agent_name(agent)
    for item in visible:
        hint_marker = _register_tool_call_report_hint(
            item,
            hint_state=hint_state,
            agent_name=agent_name,
        )
        _append_slow_tool_call_row(
            text,
            item,
            labeled=labeled,
            hint_marker=hint_marker,
            hint_marker_width=hint_marker_width,
        )

    overflow = len(slow_calls) - len(visible)
    if overflow > 0:
        text.append(
            f"  + {overflow} more \u00b7 press ] for the full tools timeline\n",
            style=COLOR_TRUNCATION,
        )


def _select_sourced_slow_tool_calls(
    sources: tuple[SlowToolSource, ...],
    *,
    now: datetime,
    threshold_ms: int,
) -> tuple[_SourcedSlowToolCall, ...]:
    selected: list[_SourcedSlowToolCall] = []
    for source_index, source in enumerate(sources):
        for slow_call in select_slow_tool_calls(
            source.entries,
            now=now,
            agent_is_active=source.agent_is_active,
            agent_end_reference=source.end_reference,
            threshold_ms=threshold_ms,
        ):
            selected.append(
                _SourcedSlowToolCall(
                    slow_call=slow_call,
                    source=source,
                    source_index=source_index,
                )
            )
    selected.sort(key=_sourced_slow_tool_call_sort_key)
    return tuple(selected)


def _select_visible_slow_tool_calls(
    slow_calls: tuple[_SourcedSlowToolCall, ...],
) -> tuple[_SourcedSlowToolCall, ...]:
    if len(slow_calls) <= MAX_VISIBLE_SLOW_TOOL_CALLS:
        return slow_calls

    running = tuple(item for item in slow_calls if item.slow_call.is_running)
    if len(running) >= MAX_VISIBLE_SLOW_TOOL_CALLS:
        visible = running[-MAX_VISIBLE_SLOW_TOOL_CALLS:]
    else:
        remaining_slots = MAX_VISIBLE_SLOW_TOOL_CALLS - len(running)
        non_running = tuple(
            item for item in slow_calls if not item.slow_call.is_running
        )
        visible = (
            *running,
            *non_running[-remaining_slots:],
        )

    return tuple(sorted(visible, key=_sourced_slow_tool_call_sort_key))


def _sourced_slow_tool_call_sort_key(
    item: _SourcedSlowToolCall,
) -> tuple[datetime, int, int]:
    return (
        item.slow_call.started_at,
        item.source_index,
        item.slow_call.entry.line_number,
    )


def _append_slow_tool_call_row(
    text: Text,
    sourced: _SourcedSlowToolCall,
    *,
    labeled: bool,
    hint_marker: str | None = None,
    hint_marker_width: int = 0,
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
    _append_hint_marker_cell(text, hint_marker, hint_marker_width)
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


def _append_hint_marker_cell(
    text: Text,
    marker: str | None,
    marker_width: int,
) -> None:
    if marker_width <= 0:
        text.append(" ")
        return
    if marker is None:
        text.append(" " * (marker_width + 2))
        return
    text.append(" ")
    text.append(_pad_cells(marker, marker_width), style=_COLOR_HINT)
    text.append(" ")


def _hint_marker_width(
    visible: tuple[_SourcedSlowToolCall, ...],
    hint_state: HeaderHintState | None,
) -> int:
    if hint_state is None:
        return 0
    report_count = sum(1 for item in visible if _is_report_hint_eligible(item))
    if not report_count:
        return 0
    largest_hint = hint_state.hint_counter + report_count - 1
    return cell_len(f"[{largest_hint}]")


def _register_tool_call_report_hint(
    sourced: _SourcedSlowToolCall,
    *,
    hint_state: HeaderHintState | None,
    agent_name: str | None,
) -> str | None:
    if hint_state is None or not _is_report_hint_eligible(sourced):
        return None

    hint_number = hint_state.hint_counter
    hint_state.hint_counter += 1
    report_path = tool_call_report_path(sourced.slow_call.entry)
    hint_state.hint_mappings[hint_number] = report_path
    hint_state.tool_call_reports[report_path] = SlowToolCallReportSpec(
        entry=sourced.slow_call.entry,
        source_label=sourced.source.label,
        agent_name=agent_name,
        report_path=report_path,
    )
    return f"[{hint_number}]"


def _is_report_hint_eligible(sourced: _SourcedSlowToolCall) -> bool:
    return sourced.slow_call.entry.status in {"success", "failure"}


def _agent_name(agent: object) -> str | None:
    value = getattr(agent, "agent_name", None) or getattr(agent, "display_name", None)
    return value if isinstance(value, str) and value else None


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

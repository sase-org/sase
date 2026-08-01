"""SLOW TOOL CALLS section rendering for the prompt panel header."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
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
from ...models.fold_scale import (
    AGENT_FOLD_SCALE,
    FoldScale,
    effective_fold_level,
)
from ...models.fold_state import FoldLevel
from ._agent_context_common import (
    COLOR_SUMMARY,
    COLOR_TIMESTAMP,
    COLOR_TRUNCATION,
    count_phrase,
    format_local_hhmmss,
    truncate_display,
)
from ._agent_display_state import HeaderHintState
from ._agent_slow_tools_detail import (
    ResponsiveSlowToolCallsSection,
    SlowToolDetail,
    SlowToolSectionRow,
    digest_target,
    prepare_slow_tool_call_details,
    slow_tool_detail_level,
)
from ._fold_language import append_fold_section_heading
from ._helpers import append_major_section_divider, append_section_heading
from ._tool_call_report_hints import (
    register_tool_call_report_hint,
    tool_call_report_hint_marker_width,
)

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
SLOW_TOOL_CALLS_SECTION_ID = "slow-tool-calls"


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
    panel_level: FoldLevel = FoldLevel.COLLAPSED,
    scale: FoldScale = AGENT_FOLD_SCALE,
    section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    responsive_ranges: MutableMapping[str, tuple[int, int]] | None = None,
) -> ResponsiveSlowToolCallsSection | None:
    """Append the SLOW TOOL CALLS section when any calls qualify."""
    overrides = section_fold_overrides or {}
    level = effective_fold_level(
        overrides.get(SLOW_TOOL_CALLS_SECTION_ID, panel_level),
        scale,
    )
    detail_level = slow_tool_detail_level(level, scale)
    return _append_slow_tool_calls_section(
        text,
        sources=sources,
        agent=agent,
        now=now,
        hint_state=hint_state,
        threshold_ms=threshold_ms,
        detail_level=detail_level,
        heading_level=level,
        heading_scale=scale,
        responsive_ranges=responsive_ranges,
    )


def append_slow_tool_calls_section_no_fold_owner(
    text: Text,
    *,
    sources: tuple[SlowToolSource, ...] | None,
    agent: object,
    now: datetime,
    hint_state: HeaderHintState | None = None,
    threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
) -> None:
    """Append the always-visible detail tier for a fold-inert aggregate."""
    _append_slow_tool_calls_section(
        text,
        sources=sources,
        agent=agent,
        now=now,
        hint_state=hint_state,
        threshold_ms=threshold_ms,
        detail_level=SlowToolDetail.DETAIL,
        heading_level=None,
        heading_scale=None,
        responsive_ranges=None,
    )


def _append_slow_tool_calls_section(
    text: Text,
    *,
    sources: tuple[SlowToolSource, ...] | None,
    agent: object,
    now: datetime,
    hint_state: HeaderHintState | None,
    threshold_ms: int,
    detail_level: SlowToolDetail,
    heading_level: FoldLevel | None,
    heading_scale: FoldScale | None,
    responsive_ranges: MutableMapping[str, tuple[int, int]] | None,
) -> ResponsiveSlowToolCallsSection | None:
    if not sources:
        return None

    threshold_ms = normalize_slow_tool_call_threshold_ms(threshold_ms)
    slow_calls = _select_sourced_slow_tool_calls(
        sources, now=now, threshold_ms=threshold_ms
    )
    if not slow_calls:
        return None

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
    section_start = len(text.plain)
    heading = Text(end="")
    if heading_level is None or heading_scale is None:
        heading_text = Text("SLOW TOOL CALLS", style=_COLOR_HEADER)
        heading_text.append(
            f" \u00b7 {' · '.join(summary_parts)}",
            style=COLOR_SUMMARY,
        )
        append_section_heading(
            heading,
            heading_text,
            section_id=SLOW_TOOL_CALLS_SECTION_ID,
        )
    else:
        append_fold_section_heading(
            heading,
            "SLOW TOOL CALLS",
            section_id=SLOW_TOOL_CALLS_SECTION_ID,
            level=heading_level,
            scale=heading_scale,
            summary=" · ".join(summary_parts),
            style=_COLOR_HEADER,
            summary_style=COLOR_SUMMARY,
        )

    visible = _select_visible_slow_tool_calls(slow_calls)
    all_details = prepare_slow_tool_call_details(
        tuple(item.slow_call for item in slow_calls)
    )
    detail_by_item_id = {
        id(item): detail for item, detail in zip(slow_calls, all_details, strict=True)
    }
    hint_marker_width = _hint_marker_width(visible, hint_state)
    agent_name = _agent_name(agent)
    rows: list[SlowToolSectionRow] = []
    for item in visible:
        hint_marker = _register_tool_call_report_hint(
            item,
            hint_state=hint_state,
            agent_name=agent_name,
        )
        row_text = Text(end="", overflow="crop", no_wrap=True)
        _append_slow_tool_call_row(
            row_text,
            item,
            labeled=labeled,
            hint_marker=hint_marker,
            hint_marker_width=hint_marker_width,
        )
        rows.append(
            SlowToolSectionRow(
                compact_line=row_text,
                detail=detail_by_item_id[id(item)],
            )
        )

    hidden_tail = None
    if detail_level == SlowToolDetail.COMPACT and any(
        row.detail.has_hidden_primary for row in rows
    ):
        hidden_tail = Text(
            "  … full commands hidden · zz / za to show\n",
            style="dim italic",
            end="",
        )

    overflow = len(slow_calls) - len(visible)
    overflow_tail = None
    if overflow > 0:
        overflow_tail = Text(
            f"  + {overflow} more \u00b7 press ] for the full tools timeline\n",
            style=COLOR_TRUNCATION,
            end="",
        )

    section = ResponsiveSlowToolCallsSection(
        heading=heading,
        rows=tuple(rows),
        detail_level=detail_level,
        hidden_tail=hidden_tail,
        overflow_tail=overflow_tail,
    )
    text.append_text(section.logical_text)
    if responsive_ranges is not None and detail_level > SlowToolDetail.COMPACT:
        responsive_ranges[SLOW_TOOL_CALLS_SECTION_ID] = (
            section_start,
            len(text.plain),
        )
    return section


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
    target = _pad_cells(digest_target(entry, target_width), target_width)
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
    return tool_call_report_hint_marker_width(
        (item.slow_call.entry for item in visible),
        hint_state,
    )


def _register_tool_call_report_hint(
    sourced: _SourcedSlowToolCall,
    *,
    hint_state: HeaderHintState | None,
    agent_name: str | None,
) -> str | None:
    return register_tool_call_report_hint(
        sourced.slow_call.entry,
        hint_state=hint_state,
        source_label=sourced.source.label,
        agent_name=agent_name,
    )


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


__all__ = [
    "SLOW_TOOL_CALLS_SECTION_ID",
    "append_slow_tool_calls_section",
    "append_slow_tool_calls_section_no_fold_owner",
]

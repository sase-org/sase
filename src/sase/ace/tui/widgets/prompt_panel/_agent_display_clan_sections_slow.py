"""Fold-aware slow-tool-call section for clan detail rows."""

from __future__ import annotations

from collections import defaultdict

from rich.text import Text

from ...llm_calls.slow import format_long_duration
from ...models._agent_clan_sections import (
    ClanSlowToolEntry,
    first_meaningful_line,
)
from ...models.fold_state import FoldLevel
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from ._agent_display_clan_sections_common import (
    append_fold_heading,
    append_member_subheading,
    append_more_tail,
)
from ._agent_display_state import HeaderHintState
from ._tool_call_report_hints import (
    register_tool_call_report_hint,
    tool_call_report_hint_marker_width,
)

_TRIAGE_SLOW_TOOL_LIMIT = 5


def append_slow_tool_calls_section(
    text: Text,
    entries: tuple[ClanSlowToolEntry, ...],
    *,
    level: FoldLevel,
    hint_state: HeaderHintState | None = None,
) -> None:
    """Render slow tools as headings, top-five triage rows, or all grouped calls."""
    append_fold_heading(
        text,
        title="SLOW TOOL CALLS",
        section_id="slow-tool-calls",
        level=level,
        count=len(entries),
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        visible_entries = entries[:_TRIAGE_SLOW_TOOL_LIMIT]
        hint_marker_width = _slow_tool_hint_marker_width(
            visible_entries,
            hint_state,
        )
        for entry in visible_entries:
            _append_slow_tool_line(
                text,
                entry,
                hint_state=hint_state,
                hint_marker_width=hint_marker_width,
            )
        append_more_tail(text, len(entries), _TRIAGE_SLOW_TOOL_LIMIT)
        return
    hint_marker_width = _slow_tool_hint_marker_width(entries, hint_state)
    grouped: dict[str, list[ClanSlowToolEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        append_member_subheading(text, member_label)
        for entry in member_entries:
            _append_slow_tool_line(
                text,
                entry,
                indent="  ",
                hint_state=hint_state,
                hint_marker_width=hint_marker_width,
            )


def _slow_tool_hint_marker_width(
    entries: tuple[ClanSlowToolEntry, ...],
    hint_state: HeaderHintState | None,
) -> int:
    return tool_call_report_hint_marker_width(
        (entry.call.entry for entry in entries),
        hint_state,
    )


def _append_slow_tool_line(
    text: Text,
    entry: ClanSlowToolEntry,
    *,
    indent: str = "",
    hint_state: HeaderHintState | None = None,
    hint_marker_width: int = 0,
) -> None:
    call = entry.call
    raw = call.entry
    state = (
        "running" if call.is_running else "incomplete" if call.did_not_complete else ""
    )
    target = raw.compact_target or raw.detail
    hint_marker = register_tool_call_report_hint(
        raw,
        hint_state=hint_state,
        source_label=entry.source_label,
        agent_name=entry.member_label,
    )
    text.append(f"{indent}• ", style="dim #D75FFF")
    if not indent:
        text.append(entry.member_label, style=_AGENT_NAME_ANNOTATION_STYLE)
        text.append(" · ", style="dim")
    _append_hint_marker_cell(text, hint_marker, hint_marker_width)
    text.append(raw.display_tool_name, style="bold #87D7FF")
    text.append(
        " · " + format_long_duration(call.effective_duration_ms),
        style="bold #FFAF5F",
    )
    if state:
        text.append(f" · {state}", style="dim #FFAF87")
    if target:
        text.append(" · " + first_meaningful_line(target, max_chars=96), style="dim")
    text.append("\n")


def _append_hint_marker_cell(
    text: Text,
    marker: str | None,
    marker_width: int,
) -> None:
    if marker_width <= 0:
        return
    if marker is None:
        text.append(" " * (marker_width + 1))
        return
    text.append(marker, style="bold #FFFF00")
    text.append(" ")

"""Fold-aware content sections for synthetic agent-clan detail rows."""

from __future__ import annotations

from collections import defaultdict

from rich.syntax import Syntax
from rich.text import Text

from sase.core.output_variable_display import var_value_preview

from ...models._agent_clan_sections import (
    ClanContextEntry,
    ClanContextLane,
    ClanDiskSection,
    ClanErrorEntry,
    ClanSectionSnapshot,
    ClanSlowToolEntry,
    ClanTextEntry,
    ClanVariableEntry,
    first_meaningful_line,
)
from ...models.fold_state import FoldLevel
from ...tools.slow import format_long_duration
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from ._fold_language import append_fold_glyph, fold_count_style
from ._helpers import append_major_section_divider, append_section_heading
from ._output_variable_rich import append_var_value_lines, var_value_style

_TRIAGE_ENTRY_LIMIT = 8
_TRIAGE_SLOW_TOOL_LIMIT = 5
_CLAN_SECTION_HEADING_STYLE = "bold #D7AF5F underline"
_CLAN_MEMBER_SUBHEADING_STYLE = "bold #D75FFF"
_CLAN_BODY_STYLE = "#D7D7FF"


def _append_fold_heading(
    text: Text,
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
    count: int | None,
) -> None:
    append_major_section_divider(text)
    heading = Text()
    append_fold_glyph(heading, level)
    heading.append(title, style=_CLAN_SECTION_HEADING_STYLE)
    if count is not None:
        heading.append(f" · {count}", style=fold_count_style(title))
    append_section_heading(text, heading, section_id=section_id)


def append_errors_section(
    text: Text,
    entries: tuple[ClanErrorEntry, ...],
    *,
    level: FoldLevel,
) -> None:
    """Render ERRORS as count-only, triage previews, or full diagnostics."""
    _append_fold_heading(
        text,
        title="ERRORS",
        section_id="errors",
        level=level,
        count=len(entries),
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_ENTRY_LIMIT]:
            _append_triage_line(text, entry.member_label, entry.preview)
        _append_more_tail(text, len(entries), _TRIAGE_ENTRY_LIMIT)
        return
    for entry in entries:
        _append_member_subheading(text, entry.member_label)
        _append_full_body(text, entry.message, style="#FF8787")
        if entry.traceback:
            text.append("  traceback\n", style="bold #FF5F5F")
            _append_traceback(text, entry.traceback)


def append_variables_section(
    text: Text,
    entries: tuple[ClanVariableEntry, ...],
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
) -> None:
    """Render variables as count-only, one-line assignments, or full values."""
    _append_fold_heading(
        text,
        title=title,
        section_id=section_id,
        level=level,
        count=len(entries),
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_ENTRY_LIMIT]:
            value = var_value_preview(entry.value, max_chars=96) or "—"
            _append_triage_line(
                text,
                f"{entry.member_label}.{entry.name}",
                value,
                separator=" = ",
                body_style=var_value_style(entry.value),
            )
        _append_more_tail(text, len(entries), _TRIAGE_ENTRY_LIMIT)
        return
    grouped: dict[str, list[ClanVariableEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        _append_member_subheading(text, member_label)
        for entry in member_entries:
            text.append(f"  {entry.name}\n", style="bold #87D7FF")
            append_var_value_lines(
                text,
                entry.value,
                first_prefix=Text("    ", style="dim"),
                continuation_prefix="    ",
            )


def append_text_section(
    text: Text,
    entries: tuple[ClanTextEntry, ...],
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
) -> None:
    """Render reply/prompt bodies as headings, previews, or full member bodies."""
    _append_fold_heading(
        text,
        title=title,
        section_id=section_id,
        level=level,
        count=len(entries),
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_ENTRY_LIMIT]:
            label = entry.member_label
            if entry.kind == "AGENT XPROMPT":
                label += " [XPROMPT]"
            _append_triage_line(
                text,
                label,
                entry.preview or "—",
                kind=entry.kind,
            )
        _append_more_tail(text, len(entries), _TRIAGE_ENTRY_LIMIT)
        return
    grouped: dict[str, list[ClanTextEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        _append_member_subheading(text, member_label)
        for entry in member_entries:
            kind_style = (
                "bold #AF87FF" if entry.kind == "AGENT XPROMPT" else "bold #87D7FF"
            )
            text.append(f"  {entry.kind}\n", style=kind_style)
            _append_full_body(text, entry.body, indent="    ")


def append_context_section(
    text: Text,
    lanes: tuple[ClanContextLane, ...],
    *,
    level: FoldLevel,
    count_known: bool,
) -> None:
    """Render SASE CONTEXT as headings, per-lane digests, or full lane items."""
    count = sum(len(lane.entries) for lane in lanes) if count_known else None
    _append_fold_heading(
        text,
        title="SASE CONTEXT",
        section_id="context",
        level=level,
        count=count,
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for lane in lanes:
            labels = [entry.label for entry in lane.entries[:4]]
            hidden = len(lane.entries) - len(labels)
            digest = ", ".join(labels)
            if hidden:
                digest += f", +{hidden} more"
            _append_triage_line(text, lane.label, digest or "—")
        return
    for lane in lanes:
        text.append(f"{lane.label}\n", style="bold #87D7FF")
        for entry in lane.entries:
            text.append("  • ", style="dim #D75FFF")
            text.append(entry.label, style=_CLAN_BODY_STYLE)
            if entry.count > 1:
                text.append(f" ×{entry.count}", style="dim")
            if entry.member_labels:
                text.append(
                    " · " + ", ".join(entry.member_labels),
                    style="dim #AF87FF",
                )
            text.append("\n")


def append_slow_tool_calls_section(
    text: Text,
    entries: tuple[ClanSlowToolEntry, ...],
    *,
    level: FoldLevel,
) -> None:
    """Render slow tools as headings, top-five triage rows, or all grouped calls."""
    _append_fold_heading(
        text,
        title="SLOW TOOL CALLS",
        section_id="slow-tool-calls",
        level=level,
        count=len(entries),
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_SLOW_TOOL_LIMIT]:
            _append_slow_tool_line(text, entry)
        _append_more_tail(text, len(entries), _TRIAGE_SLOW_TOOL_LIMIT)
        return
    grouped: dict[str, list[ClanSlowToolEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        _append_member_subheading(text, member_label)
        for entry in member_entries:
            _append_slow_tool_line(text, entry, indent="  ")


def _append_slow_tool_line(
    text: Text,
    entry: ClanSlowToolEntry,
    *,
    indent: str = "",
) -> None:
    call = entry.call
    raw = call.entry
    state = (
        "running" if call.is_running else "incomplete" if call.did_not_complete else ""
    )
    target = raw.compact_target or raw.detail
    text.append(f"{indent}• ", style="dim #D75FFF")
    if not indent:
        text.append(entry.member_label, style=_AGENT_NAME_ANNOTATION_STYLE)
        text.append(" · ", style="dim")
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


def _append_triage_line(
    text: Text,
    label: str,
    body: str,
    *,
    separator: str = " · ",
    kind: str | None = None,
    body_style: str = _CLAN_BODY_STYLE,
) -> None:
    text.append("• ", style="dim #D75FFF")
    text.append(label, style=_AGENT_NAME_ANNOTATION_STYLE)
    if kind:
        text.append(f" · {kind}", style="italic #AF87FF")
    text.append(separator, style="dim")
    text.append(
        first_meaningful_line(body, max_chars=120) or "—",
        style=body_style,
    )
    text.append("\n")


def _append_member_subheading(text: Text, label: str) -> None:
    text.append(f"{label}\n", style=_CLAN_MEMBER_SUBHEADING_STYLE)


def _append_full_body(
    text: Text,
    body: str,
    *,
    style: str = _CLAN_BODY_STYLE,
    indent: str = "  ",
) -> None:
    lines = body.splitlines() or ["—"]
    for line in lines:
        text.append(indent, style="dim")
        text.append(line or " ", style=style)
        text.append("\n")


def _append_traceback(text: Text, traceback: str) -> None:
    """Append traceback text with the regular agent panel's pytb highlighting."""
    highlighted = Syntax(
        traceback,
        "pytb",
        theme="monokai",
        word_wrap=True,
    ).highlight(traceback)
    for line in highlighted.split("\n", allow_blank=True):
        text.append("  ", style="dim")
        text.append_text(line)
        text.append("\n")


def _append_more_tail(text: Text, total: int, shown: int) -> None:
    hidden = total - min(total, shown)
    if hidden > 0:
        text.append(f"  +{hidden} more\n", style="dim italic")


def disk_section_loaded(
    snapshot: ClanSectionSnapshot,
    section: ClanDiskSection,
) -> bool:
    """Return whether the disk snapshot contains a requested clan section."""
    return snapshot.disk is not None and section in snapshot.disk.loaded_sections


def minimal_context_lanes(
    snapshot: ClanSectionSnapshot,
) -> tuple[ClanContextLane, ...]:
    """Build context lanes available before disk enrichment completes."""
    in_memory = snapshot.in_memory
    lanes: list[ClanContextLane] = []
    if in_memory.bead_ids:
        lanes.append(
            ClanContextLane(
                label="BEAD",
                entries=tuple(
                    ClanContextEntry(key=value, label=value, member_labels=())
                    for value in in_memory.bead_ids
                ),
            )
        )
    if in_memory.plan_paths:
        lanes.append(
            ClanContextLane(
                label="PLAN",
                entries=tuple(
                    ClanContextEntry(key=value, label=value, member_labels=())
                    for value in in_memory.plan_paths
                ),
            )
        )
    if in_memory.workspace_numbers:
        lanes.append(
            ClanContextLane(
                label="WORKSPACES",
                entries=tuple(
                    ClanContextEntry(
                        key=f"workspace:{value}",
                        label=f"workspace {value}",
                        member_labels=(),
                    )
                    for value in in_memory.workspace_numbers
                ),
            )
        )
    return tuple(lanes)

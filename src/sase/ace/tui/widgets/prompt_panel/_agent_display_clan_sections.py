"""Fold-aware content sections for synthetic agent-clan detail rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.glossary_reads import GlossaryReadDisplayEvent
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.core.output_variable_display import var_value_preview

from ...models._agent_clan_sections import (
    CLAN_CONTEXT_LANE_ORDER,
    ClanAgentIdentity,
    ClanContextEntry,
    ClanContextLane,
    ClanDiskSection,
    ClanErrorEntry,
    ClanSectionSnapshot,
    ClanSlowToolEntry,
    ClanTextEntry,
    ClanVariableEntry,
    clan_section_member_rows,
    first_meaningful_line,
)
from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ...tools.slow import format_long_duration
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from ._agent_clan_commits import aggregate_clan_commit_lane
from ._agent_display_clan_context import clan_context_entry_hint_target
from ._agent_display_state import CommitViewSpec, HeaderHintState
from ._agent_glossary_reads import register_glossary_read_report_hint
from ._agent_memory_reads import register_memory_read_report_hint
from ._fold_language import append_fold_glyph, fold_count_style
from ._helpers import append_major_section_divider, append_section_heading
from ._container_hint_text import container_text_with_file_hints
from ._hint_caps import HintContentBudget
from ._output_variable_rich import append_var_value_lines, var_value_style
from ._tool_call_report_hints import (
    register_tool_call_report_hint,
    tool_call_report_hint_marker_width,
)

_TRIAGE_ENTRY_LIMIT = 8
_TRIAGE_SLOW_TOOL_LIMIT = 5
_CLAN_SECTION_HEADING_STYLE = "bold #D7AF5F underline"
_CLAN_MEMBER_SUBHEADING_STYLE = "bold #D75FFF"
_CLAN_BODY_STYLE = "#D7D7FF"

type ClanMemberHintWorkspace = Callable[[ClanAgentIdentity, str], str | None]


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
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
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
            _append_triage_line(
                text,
                entry.member_label,
                entry.preview,
                member_identity=entry.member_identity,
                hint_state=hint_state,
                hint_budget=hint_budget,
                member_hint_workspace=member_hint_workspace,
            )
        _append_more_tail(text, len(entries), _TRIAGE_ENTRY_LIMIT)
        return
    for entry in entries:
        _append_member_subheading(text, entry.member_label)
        _append_full_body(
            text,
            entry.message,
            style="#FF8787",
            member_identity=entry.member_identity,
            hint_state=hint_state,
            hint_budget=hint_budget,
            member_hint_workspace=member_hint_workspace,
        )
        if entry.traceback:
            text.append("  traceback\n", style="bold #FF5F5F")
            _append_traceback(
                text,
                entry.traceback,
                member_identity=entry.member_identity,
                hint_state=hint_state,
                hint_budget=hint_budget,
                member_hint_workspace=member_hint_workspace,
            )


def append_variables_section(
    text: Text,
    entries: tuple[ClanVariableEntry, ...],
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
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
                member_identity=entry.member_identity,
                hint_state=hint_state,
                hint_budget=hint_budget,
                member_hint_workspace=member_hint_workspace,
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
            value_text = Text()
            append_var_value_lines(
                value_text,
                entry.value,
                first_prefix=Text("    ", style="dim"),
                continuation_prefix="    ",
            )
            text.append_text(
                _text_with_member_hints(
                    value_text,
                    member_identity=entry.member_identity,
                    hint_state=hint_state,
                    hint_budget=hint_budget,
                    member_hint_workspace=member_hint_workspace,
                )
            )


def append_text_section(
    text: Text,
    entries: tuple[ClanTextEntry, ...],
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
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
                member_identity=entry.member_identity,
                hint_state=hint_state,
                hint_budget=hint_budget,
                member_hint_workspace=member_hint_workspace,
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
            _append_full_body(
                text,
                entry.body,
                indent="    ",
                member_identity=entry.member_identity,
                hint_state=hint_state,
                hint_budget=hint_budget,
                member_hint_workspace=member_hint_workspace,
            )


def append_context_section(
    text: Text,
    lanes: tuple[ClanContextLane, ...],
    *,
    level: FoldLevel,
    count_known: bool,
    hint_state: HeaderHintState | None = None,
    member_workspaces: dict[str, str | None] | None = None,
    fallback_workspace: str | None = None,
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
            commit_spec = (
                next(
                    (
                        value
                        for value in entry.values
                        if isinstance(value, CommitViewSpec)
                    ),
                    None,
                )
                if lane.label == "COMMITS"
                else None
            )
            glossary_display = (
                next(
                    (
                        value
                        for value in entry.values
                        if isinstance(value, GlossaryReadDisplayEvent)
                    ),
                    None,
                )
                if lane.label == "GLOSSARY"
                else None
            )
            memory_display = (
                next(
                    (
                        value
                        for value in entry.values
                        if isinstance(value, MemoryReadDisplayEvent)
                    ),
                    None,
                )
                if lane.label == "MEMORY"
                else None
            )
            hint_target = (
                clan_context_entry_hint_target(
                    lane.label,
                    entry,
                    member_workspaces=member_workspaces or {},
                    fallback_workspace=fallback_workspace,
                )
                if hint_state is not None
                and commit_spec is None
                and glossary_display is None
                and memory_display is None
                else None
            )
            if commit_spec is not None and hint_state is not None:
                hint_number = hint_state.hint_counter
                text.append(f"[{hint_number}] ", style="bold #FFFF00")
                hint_state.commit_views[hint_number] = commit_spec
                hint_state.hint_counter += 1
            elif glossary_display is not None and hint_state is not None:
                marker = register_glossary_read_report_hint(
                    glossary_display, hint_state=hint_state
                )
                if marker is not None:
                    text.append(f"{marker} ", style="bold #FFFF00")
            elif memory_display is not None and hint_state is not None:
                marker = register_memory_read_report_hint(
                    memory_display, hint_state=hint_state
                )
                if marker is not None:
                    text.append(f"{marker} ", style="bold #FFFF00")
            elif hint_target is not None and hint_state is not None:
                hint_number = hint_state.hint_counter
                text.append(f"[{hint_number}] ", style="bold #FFFF00")
                hint_state.hint_mappings[hint_number] = hint_target
                hint_state.hint_counter += 1
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
    hint_state: HeaderHintState | None = None,
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
        _append_more_tail(text, len(entries), _TRIAGE_SLOW_TOOL_LIMIT)
        return
    hint_marker_width = _slow_tool_hint_marker_width(entries, hint_state)
    grouped: dict[str, list[ClanSlowToolEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        _append_member_subheading(text, member_label)
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


def _append_triage_line(
    text: Text,
    label: str,
    body: str,
    *,
    separator: str = " · ",
    kind: str | None = None,
    body_style: str = _CLAN_BODY_STYLE,
    member_identity: ClanAgentIdentity | None = None,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
) -> None:
    text.append("• ", style="dim #D75FFF")
    text.append(label, style=_AGENT_NAME_ANNOTATION_STYLE)
    if kind:
        text.append(f" · {kind}", style="italic #AF87FF")
    text.append(separator, style="dim")
    visible_body = first_meaningful_line(body, max_chars=120) or "—"
    body_text = Text(visible_body, style=body_style)
    text.append_text(
        _text_with_member_hints(
            body_text,
            member_identity=member_identity,
            hint_state=hint_state,
            hint_budget=hint_budget,
            member_hint_workspace=member_hint_workspace,
        )
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
    member_identity: ClanAgentIdentity | None = None,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
) -> None:
    body_text = Text()
    lines = body.splitlines() or ["—"]
    for line in lines:
        body_text.append(indent, style="dim")
        body_text.append(line or " ", style=style)
        body_text.append("\n")
    text.append_text(
        _text_with_member_hints(
            body_text,
            member_identity=member_identity,
            hint_state=hint_state,
            hint_budget=hint_budget,
            member_hint_workspace=member_hint_workspace,
        )
    )


def _append_traceback(
    text: Text,
    traceback: str,
    *,
    member_identity: ClanAgentIdentity | None = None,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
) -> None:
    """Append traceback text with the regular agent panel's pytb highlighting."""
    highlighted = Syntax(
        traceback,
        "pytb",
        theme="monokai",
        word_wrap=True,
    ).highlight(traceback)
    traceback_text = Text()
    for line in highlighted.split("\n", allow_blank=True):
        traceback_text.append("  ", style="dim")
        traceback_text.append_text(line)
        traceback_text.append("\n")
    text.append_text(
        _text_with_member_hints(
            traceback_text,
            member_identity=member_identity,
            hint_state=hint_state,
            hint_budget=hint_budget,
            member_hint_workspace=member_hint_workspace,
        )
    )


def _text_with_member_hints(
    content: Text,
    *,
    member_identity: ClanAgentIdentity | None,
    hint_state: HeaderHintState | None,
    hint_budget: HintContentBudget | None,
    member_hint_workspace: ClanMemberHintWorkspace | None,
) -> Text:
    """Annotate one visible body fragment against its owning member."""
    if member_identity is None or hint_state is None or member_hint_workspace is None:
        return content
    return container_text_with_file_hints(
        content,
        hint_state,
        workspace_dir=member_hint_workspace(member_identity, content.plain),
        budget=hint_budget,
    )


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
    agent: Agent,
) -> tuple[ClanContextLane, ...]:
    """Build context lanes available before disk enrichment completes."""
    in_memory = snapshot.in_memory
    lanes_by_label: dict[str, ClanContextLane] = {}
    if in_memory.bead_ids:
        lanes_by_label["BEAD"] = ClanContextLane(
            label="BEAD",
            entries=tuple(
                ClanContextEntry(key=value, label=value, member_labels=())
                for value in in_memory.bead_ids
            ),
        )
    if in_memory.plan_paths:
        lanes_by_label["PLAN"] = ClanContextLane(
            label="PLAN",
            entries=tuple(
                ClanContextEntry(
                    key=value,
                    label=value,
                    member_labels=(),
                    values=(value,),
                )
                for value in in_memory.plan_paths
            ),
        )
    commit_lane = aggregate_clan_commit_lane(
        clan_section_member_rows(agent),
        labels={member.identity: member.label for member in in_memory.members},
    )
    if commit_lane is not None:
        lanes_by_label["COMMITS"] = commit_lane
    if in_memory.workspace_numbers:
        lanes_by_label["WORKSPACES"] = ClanContextLane(
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
    return tuple(
        lanes_by_label[label]
        for label in CLAN_CONTEXT_LANE_ORDER
        if label in lanes_by_label
    )

"""Fold-aware tribe metadata documents for whole-panel focus."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.tools.slow import format_long_duration
from sase.telemetry.render import format_duration

from ...agent_count_chip import format_agent_count_chip
from ...models._agent_clan_sections import (
    ClanErrorEntry,
    ClanVariableEntry,
    first_meaningful_line,
)
from ...models.agent_tribe_summary import (
    AgentTribeSummarySnapshot,
    TribeAttentionEntry,
    TribeStatusCounts,
)
from ...models.fold_scale import TRIBE_FOLD_SCALE, fold_scale_position
from ...models.fold_state import FoldLevel
from ._helpers import append_major_section_divider, append_section_heading
from ._agent_tribe_aggregation import (
    TribeEnrichmentSection,
    TribeRuntimeStatistics,
    TribeSectionSnapshot,
    TribeSlowToolEntry,
    TribeTextEntry,
)
from ._member_roster import (
    MemberJumpMap,
    MemberRosterChild,
    MemberRosterEntry,
    MemberRosterStatusCounts,
    append_member_roster,
)

TRIBE_IDENTITY_COLOR = "#FFD75F"

_FIELD_LABEL_STYLE = "bold #87D7FF"
_TRIBE_HEADING_STYLE = f"bold {TRIBE_IDENTITY_COLOR} underline"
_SECTION_HEADING_STYLE = f"bold {TRIBE_IDENTITY_COLOR} underline"
_BODY_STYLE = "#D7D7FF"
_TRIAGE_LIMIT = 8
_FOLD_CHARS: dict[FoldLevel, str] = {
    FoldLevel.COLLAPSED: "▸",
    FoldLevel.EXPANDED: "▾",
    FoldLevel.FULLY_EXPANDED: "▼",
    FoldLevel.EXHAUSTIVE: "◆",
}
_FOLD_STYLES: dict[FoldLevel, str] = {
    FoldLevel.COLLAPSED: "#5F5F5F",
    FoldLevel.EXPANDED: "#00D7AF",
    FoldLevel.FULLY_EXPANDED: "bold #87FFD7",
    FoldLevel.EXHAUSTIVE: "bold #FFFFFF",
}
_STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}


@dataclass(frozen=True, slots=True)
class _TribeSectionIds:
    attention: str = "tribe:needs-attention"
    members: str = "tribe:members"
    errors: str = "tribe:errors"
    output_variables: str = "tribe:output-variables"
    workflow_variables: str = "tribe:workflow-variables"
    replies: str = "tribe:replies"
    slow_tool_calls: str = "tribe:slow-tool-calls"
    runtime_statistics: str = "tribe:runtime-statistics"


_SECTIONS = _TribeSectionIds()


def _effective_level(
    section_id: str,
    panel_level: FoldLevel,
    overrides: Mapping[str, FoldLevel],
) -> FoldLevel:
    from ...models.fold_scale import effective_fold_level

    return effective_fold_level(
        overrides.get(section_id, panel_level),
        TRIBE_FOLD_SCALE,
    )


def _append_fold_heading(
    text: Text,
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
    count: int | None,
    unknown_label: str | None = None,
) -> None:
    append_major_section_divider(text)
    heading = Text()
    heading.append(f"{_FOLD_CHARS[level]} ", style=_FOLD_STYLES[level])
    heading.append(title, style=_SECTION_HEADING_STYLE)
    if count is not None:
        heading.append(f" · {count}", style="dim")
    elif unknown_label:
        heading.append(f" · {unknown_label}", style="dim italic")
    append_section_heading(text, heading, section_id=section_id)


def tribe_enrichment_sections_for_fold_state(
    panel_level: FoldLevel,
    overrides: Mapping[str, FoldLevel] | None = None,
) -> frozenset[TribeEnrichmentSection]:
    """Return off-thread sections needed by the effective tribe folds."""
    fold_overrides = overrides or {}
    required: set[TribeEnrichmentSection] = set()
    if _effective_level(_SECTIONS.replies, panel_level, fold_overrides) in {
        FoldLevel.FULLY_EXPANDED,
        FoldLevel.EXHAUSTIVE,
    }:
        required.add("replies")
    if _effective_level(_SECTIONS.slow_tool_calls, panel_level, fold_overrides) in {
        FoldLevel.FULLY_EXPANDED,
        FoldLevel.EXHAUSTIVE,
    }:
        required.add("slow-tool-calls")
    if (
        _effective_level(
            _SECTIONS.runtime_statistics,
            panel_level,
            fold_overrides,
        )
        is FoldLevel.EXHAUSTIVE
    ):
        required.add("runtime-statistics")
    return frozenset(required)


def _append_count_chip(text: Text, counts: TribeStatusCounts) -> None:
    chip = format_agent_count_chip(
        stopped=counts.stopped,
        running=counts.running,
        waiting=counts.waiting,
        failed=counts.failed,
        unread=counts.unread,
        done=counts.done,
    )
    if chip.cell_len:
        text.append(" ")
        text.append_text(chip)


def _append_header(
    text: Text,
    snapshot: AgentTribeSummarySnapshot,
    fold_level: FoldLevel,
) -> None:
    text.append("TRIBE\n", style=_TRIBE_HEADING_STYLE)
    text.append("Name: ", style=_FIELD_LABEL_STYLE)
    text.append(f"{snapshot.label}\n", style=f"bold {TRIBE_IDENTITY_COLOR}")

    text.append("Status: ", style=_FIELD_LABEL_STYLE)
    from sase.agent.status_buckets import status_bucket_for_values

    bucket = status_bucket_for_values(snapshot.status)
    text.append(snapshot.status, style=_STATUS_STYLES.get(bucket, "bold"))
    _append_count_chip(text, snapshot.counts)
    text.append("\n")

    text.append("Composition: ", style=_FIELD_LABEL_STYLE)
    text.append(
        f"{snapshot.clan_count} clan{'s' if snapshot.clan_count != 1 else ''}"
        f" · {snapshot.family_count} "
        f"famil{'ies' if snapshot.family_count != 1 else 'y'}"
        f" · {snapshot.agent_count} "
        f"agent{'s' if snapshot.agent_count != 1 else ''}"
        f" · {snapshot.nested_count} nested\n",
        style=_BODY_STYLE,
    )
    text.append("Runtime: ", style=_FIELD_LABEL_STYLE)
    text.append(f"{snapshot.runtime_span}\n", style="bold #BCBCBC")
    text.append("Panel: ", style=_FIELD_LABEL_STYLE)
    text.append(
        "collapsed\n" if snapshot.panel_collapsed else "expanded\n",
        style=f"bold {TRIBE_IDENTITY_COLOR}",
    )
    position, size = fold_scale_position(fold_level, TRIBE_FOLD_SCALE)
    text.append("Fold: ", style=_FIELD_LABEL_STYLE)
    text.append(f"{position}/{size}\n", style="dim #D75FFF")


def _append_attention(
    text: Text,
    entries: tuple[TribeAttentionEntry, ...],
    *,
    level: FoldLevel,
) -> None:
    _append_fold_heading(
        text,
        title="NEEDS ATTENTION",
        section_id=_SECTIONS.attention,
        level=level,
        count=len(entries),
    )
    shown = entries if level is FoldLevel.EXHAUSTIVE else entries[:_TRIAGE_LIMIT]
    if not shown:
        text.append("  No failed, stopped, or waiting units.\n", style="dim italic")
        return
    for entry in shown:
        text.append("• ", style=_STATUS_STYLES.get(entry.status_bucket, "dim"))
        text.append(entry.unit_label, style=f"bold {TRIBE_IDENTITY_COLOR}")
        text.append(" · ", style="dim")
        text.append(
            entry.status,
            style=_STATUS_STYLES.get(entry.status_bucket, "bold"),
        )
        text.append(" · ", style="dim")
        text.append(entry.preview, style=_BODY_STYLE)
        text.append("\n")
    _append_more_tail(text, len(entries), len(shown))


def _roster_entries(
    snapshot: AgentTribeSummarySnapshot,
) -> tuple[MemberRosterEntry, ...]:
    entries: list[MemberRosterEntry] = []
    for unit in snapshot.units:
        counts = unit.status_counts
        entries.append(
            MemberRosterEntry(
                identity=unit.identity,
                presented_name=unit.presented_name,
                label=unit.label,
                kind=unit.kind,
                status=unit.status,
                model=unit.model,
                duration=unit.duration,
                digest=unit.digest,
                children=tuple(
                    MemberRosterChild(
                        label=child.label,
                        kind=child.kind,
                        status=child.status,
                        model=child.model,
                        duration=child.duration,
                        digest=child.digest,
                        is_marked=child.is_marked,
                        is_unread=child.is_unread,
                    )
                    for child in unit.children
                ),
                status_counts=(
                    MemberRosterStatusCounts(
                        stopped=counts.stopped,
                        running=counts.running,
                        waiting=counts.waiting,
                        failed=counts.failed,
                        unread=counts.unread,
                        done=counts.done,
                    )
                    if counts is not None
                    else None
                ),
                is_marked=unit.is_marked,
                is_unread=unit.is_unread,
            )
        )
    return tuple(entries)


def _append_errors(
    text: Text,
    entries: tuple[ClanErrorEntry, ...],
    *,
    level: FoldLevel,
) -> None:
    _append_fold_heading(
        text,
        title="ERRORS",
        section_id=_SECTIONS.errors,
        level=level,
        count=len(entries),
    )
    if level is FoldLevel.COLLAPSED:
        return
    if level is not FoldLevel.EXHAUSTIVE:
        for entry in entries[:_TRIAGE_LIMIT]:
            _append_triage_line(text, entry.member_label, entry.preview)
        _append_more_tail(text, len(entries), _TRIAGE_LIMIT)
        return
    for entry in entries:
        text.append(f"{entry.member_label}\n", style="bold #D75FFF")
        _append_full_body(text, entry.message, style="#FF8787")
        if entry.traceback:
            text.append("  traceback\n", style="bold #FF5F5F")
            _append_traceback(text, entry.traceback)


def _append_variables(
    text: Text,
    entries: tuple[ClanVariableEntry, ...],
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
) -> None:
    _append_fold_heading(
        text,
        title=title,
        section_id=section_id,
        level=level,
        count=len(entries),
    )
    if level is FoldLevel.COLLAPSED:
        return
    if level is not FoldLevel.EXHAUSTIVE:
        for entry in entries[:_TRIAGE_LIMIT]:
            preview = first_meaningful_line(entry.value, max_chars=96) or "—"
            _append_triage_line(
                text,
                f"{entry.member_label}.{entry.name}",
                preview,
                separator=" = ",
            )
        _append_more_tail(text, len(entries), _TRIAGE_LIMIT)
        return
    grouped: dict[str, list[ClanVariableEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        text.append(f"{member_label}\n", style="bold #D75FFF")
        for entry in member_entries:
            text.append(f"  {entry.name}\n", style="bold #87D7FF")
            _append_full_body(text, entry.value, indent="    ")


def _append_replies(
    text: Text,
    snapshot: TribeSectionSnapshot | None,
    *,
    level: FoldLevel,
    required: frozenset[TribeEnrichmentSection],
) -> None:
    disk = snapshot.disk if snapshot is not None else None
    loaded = disk is not None and "replies" in disk.loaded_sections
    entries = disk.replies if loaded and disk is not None else ()
    loading = (snapshot is not None and "replies" in snapshot.loading_sections) or (
        "replies" in required and not loaded
    )
    _append_fold_heading(
        text,
        title="REPLIES",
        section_id=_SECTIONS.replies,
        level=level,
        count=len(entries) if loaded else None,
        unknown_label="loading…" if loading else "—",
    )
    if level in {FoldLevel.COLLAPSED, FoldLevel.EXPANDED}:
        return
    if not loaded:
        _append_loading(text)
        return
    if not entries:
        _append_empty(text)
        return
    if level is FoldLevel.FULLY_EXPANDED:
        for item in entries[:_TRIAGE_LIMIT]:
            _append_triage_line(
                text,
                _tribe_member_label(item.unit_label, item.entry.member_label),
                item.entry.preview,
            )
        _append_more_tail(text, len(entries), _TRIAGE_LIMIT)
        return
    grouped: dict[str, list[TribeTextEntry]] = defaultdict(list)
    for item in entries:
        grouped[item.unit_label].append(item)
    for unit_label, unit_entries in grouped.items():
        text.append(f"{unit_label}\n", style=f"bold {TRIBE_IDENTITY_COLOR}")
        by_member: dict[str, list[TribeTextEntry]] = defaultdict(list)
        for item in unit_entries:
            by_member[item.entry.member_label].append(item)
        for member_label, member_entries in by_member.items():
            text.append(f"  {member_label}\n", style="bold #D75FFF")
            for item in member_entries:
                text.append(f"    {item.entry.kind}\n", style="bold #87D7FF")
                _append_full_body(text, item.entry.body, indent="      ")


def _append_slow_tool_calls(
    text: Text,
    snapshot: TribeSectionSnapshot | None,
    *,
    level: FoldLevel,
    required: frozenset[TribeEnrichmentSection],
) -> None:
    disk = snapshot.disk if snapshot is not None else None
    loaded = disk is not None and "slow-tool-calls" in disk.loaded_sections
    entries = disk.slow_tool_calls if loaded and disk is not None else ()
    loading = (
        snapshot is not None and "slow-tool-calls" in snapshot.loading_sections
    ) or ("slow-tool-calls" in required and not loaded)
    _append_fold_heading(
        text,
        title="SLOW TOOL CALLS",
        section_id=_SECTIONS.slow_tool_calls,
        level=level,
        count=len(entries) if loaded else None,
        unknown_label="loading…" if loading else "—",
    )
    if level in {FoldLevel.COLLAPSED, FoldLevel.EXPANDED}:
        return
    if not loaded:
        _append_loading(text)
        return
    if not entries:
        _append_empty(text)
        return
    if level is FoldLevel.FULLY_EXPANDED:
        for item in entries[:_TRIAGE_LIMIT]:
            _append_tribe_slow_tool_line(text, item)
        _append_more_tail(text, len(entries), _TRIAGE_LIMIT)
        return
    grouped: dict[str, list[TribeSlowToolEntry]] = defaultdict(list)
    for item in entries:
        grouped[item.unit_label].append(item)
    for unit_label, unit_entries in grouped.items():
        text.append(f"{unit_label}\n", style=f"bold {TRIBE_IDENTITY_COLOR}")
        for item in unit_entries:
            _append_tribe_slow_tool_line(text, item, indent="  ")


def _append_runtime_statistics(
    text: Text,
    snapshot: TribeSectionSnapshot | None,
    *,
    level: FoldLevel,
    required: frozenset[TribeEnrichmentSection],
) -> None:
    if level is not FoldLevel.EXHAUSTIVE:
        return
    loaded = snapshot is not None and snapshot.runtime_statistics_loaded
    loading = (
        snapshot is not None and "runtime-statistics" in snapshot.loading_sections
    ) or ("runtime-statistics" in required and not loaded)
    _append_fold_heading(
        text,
        title="RUNTIME STATISTICS",
        section_id=_SECTIONS.runtime_statistics,
        level=level,
        count=None,
        unknown_label="loading…" if loading else None,
    )
    if not loaded:
        _append_loading(text)
        return
    stats = snapshot.runtime_statistics if snapshot is not None else None
    if stats is None:
        _append_empty(text)
        return
    _append_runtime_statistics_body(text, stats)


def _append_runtime_statistics_body(
    text: Text,
    stats: TribeRuntimeStatistics,
) -> None:
    text.append("Runs: ", style=_FIELD_LABEL_STYLE)
    text.append(str(stats.runs), style="bold #87FFD7")
    text.append(" · Share: ", style=_FIELD_LABEL_STYLE)
    text.append(f"{stats.share:.1%}\n", style="bold #87FFD7")
    text.append("Total: ", style=_FIELD_LABEL_STYLE)
    text.append(format_duration(stats.total_seconds), style=_BODY_STYLE)
    for label, value in (
        ("Mean", stats.mean_seconds),
        ("p50", stats.p50_seconds),
        ("p95", stats.p95_seconds),
        ("Max", stats.max_seconds),
    ):
        text.append(f" · {label}: ", style=_FIELD_LABEL_STYLE)
        text.append(format_duration(value), style=_BODY_STYLE)
    text.append("\n")


def _append_tribe_slow_tool_line(
    text: Text,
    item: TribeSlowToolEntry,
    *,
    indent: str = "",
) -> None:
    entry = item.entry
    call = entry.call
    raw = call.entry
    state = (
        "running" if call.is_running else "incomplete" if call.did_not_complete else ""
    )
    text.append(f"{indent}• ", style="dim #D75FFF")
    if not indent:
        text.append(
            _tribe_member_label(item.unit_label, entry.member_label),
            style=f"bold {TRIBE_IDENTITY_COLOR}",
        )
        text.append(" · ", style="dim")
    else:
        text.append(entry.member_label, style="bold #D75FFF")
        text.append(" · ", style="dim")
    text.append(raw.display_tool_name, style="bold #87D7FF")
    text.append(
        " · " + format_long_duration(call.effective_duration_ms),
        style="bold #FFAF5F",
    )
    if state:
        text.append(f" · {state}", style="dim #FFAF87")
    target = raw.compact_target or raw.detail
    if target:
        text.append(" · " + first_meaningful_line(target, max_chars=96), style="dim")
    text.append("\n")


def _tribe_member_label(unit_label: str, member_label: str) -> str:
    if member_label == unit_label:
        return unit_label
    return f"{unit_label} › {member_label}"


def _append_loading(text: Text) -> None:
    text.append("  loading…\n", style="dim italic")


def _append_empty(text: Text) -> None:
    text.append("  —\n", style="dim")


def _append_triage_line(
    text: Text,
    label: str,
    body: str,
    *,
    separator: str = " · ",
) -> None:
    text.append("• ", style="dim #D75FFF")
    text.append(label, style=f"bold {TRIBE_IDENTITY_COLOR}")
    text.append(separator, style="dim")
    text.append(first_meaningful_line(body) or "—", style=_BODY_STYLE)
    text.append("\n")


def _append_full_body(
    text: Text,
    body: str,
    *,
    style: str = _BODY_STYLE,
    indent: str = "  ",
) -> None:
    for line in body.splitlines() or ["—"]:
        text.append(indent, style="dim")
        text.append(line or " ", style=style)
        text.append("\n")


def _append_traceback(text: Text, traceback: str) -> None:
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


def build_tribe_detail_text(
    snapshot: AgentTribeSummarySnapshot,
    *,
    section_snapshot: TribeSectionSnapshot | None = None,
    fold_level: FoldLevel = FoldLevel.COLLAPSED,
    section_fold_overrides: Mapping[str, FoldLevel] | None = None,
    member_jump_map_publisher: Callable[[MemberJumpMap], None] | None = None,
    cheap: bool = False,
) -> Text:
    """Build a fold-aware tribe document without filesystem access."""
    overrides = section_fold_overrides or {}
    required = tribe_enrichment_sections_for_fold_state(fold_level, overrides)
    text = Text()
    _append_header(text, snapshot, fold_level)
    if cheap:
        return text

    _append_attention(
        text,
        snapshot.attention,
        level=_effective_level(_SECTIONS.attention, fold_level, overrides),
    )
    jump_map = append_member_roster(
        text,
        container_identity=snapshot.container_identity,
        entries=_roster_entries(snapshot),
        title="TRIBE MEMBERS",
        accent=TRIBE_IDENTITY_COLOR,
        panel_level=fold_level,
        section_fold_overrides=overrides,
        fold_scale=TRIBE_FOLD_SCALE,
        section_id=_SECTIONS.members,
        member_anchor_prefix="tribe:member:",
        heading_only_when_collapsed=True,
        show_empty_heading=True,
        children_from_level=FoldLevel.FULLY_EXPANDED,
        full_annotations_from_level=FoldLevel.EXHAUSTIVE,
    )
    if member_jump_map_publisher is not None:
        member_jump_map_publisher(jump_map)

    _append_errors(
        text,
        snapshot.errors,
        level=_effective_level(_SECTIONS.errors, fold_level, overrides),
    )
    _append_variables(
        text,
        snapshot.output_variables,
        title="OUTPUT VARIABLES",
        section_id=_SECTIONS.output_variables,
        level=_effective_level(_SECTIONS.output_variables, fold_level, overrides),
    )
    _append_variables(
        text,
        snapshot.workflow_variables,
        title="WORKFLOW VARIABLES",
        section_id=_SECTIONS.workflow_variables,
        level=_effective_level(_SECTIONS.workflow_variables, fold_level, overrides),
    )
    _append_replies(
        text,
        section_snapshot,
        level=_effective_level(_SECTIONS.replies, fold_level, overrides),
        required=required,
    )
    _append_slow_tool_calls(
        text,
        section_snapshot,
        level=_effective_level(_SECTIONS.slow_tool_calls, fold_level, overrides),
        required=required,
    )
    _append_runtime_statistics(
        text,
        section_snapshot,
        level=_effective_level(
            _SECTIONS.runtime_statistics,
            fold_level,
            overrides,
        ),
        required=required,
    )
    return text


__all__ = [
    "TRIBE_IDENTITY_COLOR",
    "build_tribe_detail_text",
    "tribe_enrichment_sections_for_fold_state",
]

"""Fold-aware detail sections for tribe documents."""

from __future__ import annotations

from collections import defaultdict

from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.tools.slow import format_long_duration
from sase.core.output_variable_display import var_value_preview
from sase.telemetry.render import format_duration

from ...models._agent_clan_sections import (
    ClanErrorEntry,
    ClanVariableEntry,
    first_meaningful_line,
)
from ...models.agent_tribe_summary import TribeAttentionEntry
from ...models.fold_state import FoldLevel
from ._agent_display_tribe_common import (
    BODY_STYLE,
    FIELD_LABEL_STYLE,
    SECTIONS,
    STATUS_STYLES,
    TRIAGE_LIMIT,
    TRIBE_IDENTITY_COLOR,
    append_fold_heading,
    append_more_tail,
)
from ._agent_tribe_aggregation import (
    TribeRuntimeStatistics,
    TribeSectionSnapshot,
    TribeSlowToolEntry,
    TribeTextEntry,
)
from ._output_variable_rich import append_var_value_lines, var_value_style


def append_attention(
    text: Text,
    entries: tuple[TribeAttentionEntry, ...],
    *,
    level: FoldLevel,
) -> None:
    if not entries:
        return
    append_fold_heading(
        text,
        title="NEEDS ATTENTION",
        section_id=SECTIONS.attention,
        level=level,
        count=len(entries),
    )
    shown = entries if level is FoldLevel.EXHAUSTIVE else entries[:TRIAGE_LIMIT]
    for entry in shown:
        text.append("• ", style=STATUS_STYLES.get(entry.status_bucket, "dim"))
        text.append(entry.unit_label, style=f"bold {TRIBE_IDENTITY_COLOR}")
        text.append(" · ", style="dim")
        text.append(
            entry.status,
            style=STATUS_STYLES.get(entry.status_bucket, "bold"),
        )
        text.append(" · ", style="dim")
        text.append(entry.preview, style=BODY_STYLE)
        text.append("\n")
    append_more_tail(text, len(entries), len(shown))


def append_errors(
    text: Text,
    entries: tuple[ClanErrorEntry, ...],
    *,
    level: FoldLevel,
) -> None:
    if not entries:
        return
    append_fold_heading(
        text,
        title="ERRORS",
        section_id=SECTIONS.errors,
        level=level,
        count=len(entries),
    )
    if level is FoldLevel.COLLAPSED:
        return
    if level is FoldLevel.EXPANDED:
        for entry in entries[:TRIAGE_LIMIT]:
            _append_triage_line(text, entry.member_label, entry.preview)
        append_more_tail(text, len(entries), TRIAGE_LIMIT)
        return
    shown = entries if level is FoldLevel.EXHAUSTIVE else entries[:TRIAGE_LIMIT]
    grouped: dict[str, list[ClanErrorEntry]] = defaultdict(list)
    for entry in shown:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        text.append(f"{member_label}\n", style="bold #D75FFF")
        for entry in member_entries:
            _append_full_body(text, entry.message, style="#FF8787")
            if level is FoldLevel.EXHAUSTIVE and entry.traceback:
                text.append("  traceback\n", style="bold #FF5F5F")
                _append_traceback(text, entry.traceback)
    append_more_tail(text, len(entries), len(shown))


def append_variables(
    text: Text,
    entries: tuple[ClanVariableEntry, ...],
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
) -> None:
    if not entries:
        return
    append_fold_heading(
        text,
        title=title,
        section_id=section_id,
        level=level,
        count=len(entries),
    )
    if level is FoldLevel.COLLAPSED:
        return
    if level is FoldLevel.EXPANDED:
        for entry in entries[:TRIAGE_LIMIT]:
            preview = var_value_preview(entry.value, max_chars=96) or "—"
            _append_triage_line(
                text,
                f"{entry.member_label}.{entry.name}",
                preview,
                separator=" = ",
                body_style=var_value_style(entry.value),
            )
        append_more_tail(text, len(entries), TRIAGE_LIMIT)
        return
    shown = entries if level is FoldLevel.EXHAUSTIVE else entries[:TRIAGE_LIMIT]
    grouped: dict[str, list[ClanVariableEntry]] = defaultdict(list)
    for entry in shown:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        text.append(f"{member_label}\n", style="bold #D75FFF")
        for entry in member_entries:
            text.append(f"  {entry.name}\n", style="bold #87D7FF")
            append_var_value_lines(
                text,
                entry.value,
                first_prefix=Text("    ", style="dim"),
                continuation_prefix="    ",
            )
    append_more_tail(text, len(entries), len(shown))


def append_replies(
    text: Text,
    snapshot: TribeSectionSnapshot | None,
    *,
    level: FoldLevel,
) -> None:
    disk = snapshot.disk if snapshot is not None else None
    loaded = disk is not None and "replies" in disk.loaded_sections
    entries = disk.replies if loaded and disk is not None else ()
    if not loaded or not entries:
        return
    append_fold_heading(
        text,
        title="REPLIES",
        section_id=SECTIONS.replies,
        level=level,
        count=len(entries),
    )
    if level is FoldLevel.COLLAPSED:
        return
    if level is FoldLevel.EXPANDED:
        for item in entries[:TRIAGE_LIMIT]:
            _append_triage_line(
                text,
                _tribe_member_label(item.unit_label, item.entry.member_label),
                item.entry.preview,
            )
        append_more_tail(text, len(entries), TRIAGE_LIMIT)
        return
    shown = entries if level is FoldLevel.EXHAUSTIVE else entries[:TRIAGE_LIMIT]
    grouped: dict[str, list[TribeTextEntry]] = defaultdict(list)
    for item in shown:
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
    append_more_tail(text, len(entries), len(shown))


def append_slow_tool_calls(
    text: Text,
    snapshot: TribeSectionSnapshot | None,
    *,
    level: FoldLevel,
) -> None:
    disk = snapshot.disk if snapshot is not None else None
    loaded = disk is not None and "slow-tool-calls" in disk.loaded_sections
    entries = disk.slow_tool_calls if loaded and disk is not None else ()
    if not loaded or not entries:
        return
    append_fold_heading(
        text,
        title="SLOW TOOL CALLS",
        section_id=SECTIONS.slow_tool_calls,
        level=level,
        count=len(entries),
    )
    if level is FoldLevel.COLLAPSED:
        return
    if level is FoldLevel.EXPANDED:
        for item in entries[:TRIAGE_LIMIT]:
            _append_tribe_slow_tool_line(text, item)
        append_more_tail(text, len(entries), TRIAGE_LIMIT)
        return
    shown = entries if level is FoldLevel.EXHAUSTIVE else entries[:TRIAGE_LIMIT]
    grouped: dict[str, list[TribeSlowToolEntry]] = defaultdict(list)
    for item in shown:
        grouped[item.unit_label].append(item)
    for unit_label, unit_entries in grouped.items():
        text.append(f"{unit_label}\n", style=f"bold {TRIBE_IDENTITY_COLOR}")
        for item in unit_entries:
            _append_tribe_slow_tool_line(text, item, indent="  ")
    append_more_tail(text, len(entries), len(shown))


def append_runtime_statistics(
    text: Text,
    snapshot: TribeSectionSnapshot | None,
    *,
    level: FoldLevel,
) -> None:
    if level is not FoldLevel.EXHAUSTIVE:
        return
    loaded = snapshot is not None and snapshot.runtime_statistics_loaded
    stats = snapshot.runtime_statistics if snapshot is not None else None
    if not loaded or stats is None:
        return
    append_fold_heading(
        text,
        title="RUNTIME STATISTICS",
        section_id=SECTIONS.runtime_statistics,
        level=level,
        count=None,
    )
    _append_runtime_statistics_body(text, stats)


def _append_runtime_statistics_body(
    text: Text,
    stats: TribeRuntimeStatistics,
) -> None:
    text.append("Runs: ", style=FIELD_LABEL_STYLE)
    text.append(str(stats.runs), style="bold #87FFD7")
    text.append(" · Share: ", style=FIELD_LABEL_STYLE)
    text.append(f"{stats.share:.1%}\n", style="bold #87FFD7")
    text.append("Total: ", style=FIELD_LABEL_STYLE)
    text.append(format_duration(stats.total_seconds), style=BODY_STYLE)
    for label, value in (
        ("Mean", stats.mean_seconds),
        ("p50", stats.p50_seconds),
        ("p95", stats.p95_seconds),
        ("Max", stats.max_seconds),
    ):
        text.append(f" · {label}: ", style=FIELD_LABEL_STYLE)
        text.append(format_duration(value), style=BODY_STYLE)
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


def _append_triage_line(
    text: Text,
    label: str,
    body: str,
    *,
    separator: str = " · ",
    body_style: str = BODY_STYLE,
) -> None:
    text.append("• ", style="dim #D75FFF")
    text.append(label, style=f"bold {TRIBE_IDENTITY_COLOR}")
    text.append(separator, style="dim")
    text.append(first_meaningful_line(body) or "—", style=body_style)
    text.append("\n")


def _append_full_body(
    text: Text,
    body: str,
    *,
    style: str = BODY_STYLE,
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

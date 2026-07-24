"""Rendering helpers for saved dismissed-agent group revival."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from rich.cells import cell_len
from rich.text import Text

from sase.core.agent_group_archive_wire import (
    SavedAgentGroupRefWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
)
from sase.project_display_names import (
    humanize_vcs_refs_in_text,
    project_display_name_for,
)

from ..models.agent_status import STOPPED_COLOR, STOPPED_STATUS

_STATUS_COLORS: dict[str, str] = {
    "DONE": "#5FD75F",
    "FAILED": "#FF5F5F",
    STOPPED_STATUS: STOPPED_COLOR,
    "WAITING INPUT": "#FF87D7",
    "RUNNING": "#87AFFF",
}
_ROW_AGE_WIDTH = 4
_ROW_AGENT_COUNT_WIDTH = 4
_STATUS_BADGE_WIDTH = 7
_STATUS_BADGE_PRIORITY = ("FAILED", "RUNNING", "DONE")
_TITLE_AGENT_COUNT_RE = re.compile(r"^\d+\s+agents?(?=$|\s)")
_STATUS_GLYPHS: dict[str, str] = {
    "FAILED": "x",
    "RUNNING": "●",
    "DONE": "✓",
    STOPPED_STATUS: "Ø",
    "WAITING INPUT": "!",
}


def _saved_group_time_label(created_at: str, *, now: datetime | None = None) -> str:
    """Return a compact relative+absolute saved-time label."""

    parsed = _parse_timestamp(created_at)
    if parsed is None:
        return created_at

    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    delta_seconds = max(0, int((reference - parsed).total_seconds()))
    if delta_seconds < 60:
        relative = "just now"
    elif delta_seconds < 3600:
        relative = f"{delta_seconds // 60}m ago"
    elif delta_seconds < 86400:
        relative = f"{delta_seconds // 3600}h ago"
    else:
        relative = f"{delta_seconds // 86400}d ago"
    return f"{relative} | {parsed.strftime('%Y-%m-%d %H:%M')}"


def apply_jump_hint_prefix(label: Text, hint: str) -> Text:
    """Prefix a selectable row label with an adaptive jump hint marker.

    Builds a fresh ``Text`` so the original styled label, its ``no_wrap``
    flag, and its overflow behavior are preserved while a ``[N] `` hint
    marker is rendered ahead of it.
    """

    decorated = Text(no_wrap=label.no_wrap, overflow=label.overflow)
    decorated.append("[", style="dim")
    decorated.append(hint, style="bold #FFFF00")
    decorated.append("] ", style="dim")
    decorated.append_text(label)
    return decorated


def format_saved_group_row(
    summary: SavedAgentGroupSummaryWire,
    *,
    now: datetime | None = None,
) -> Text:
    """Build one saved-group list row."""

    text = Text(no_wrap=True, overflow="ellipsis")
    text.append("* " if summary.revived_at else "  ", style="dim")
    text.append(_row_age_label(summary.created_at, now=now), style="dim")
    text.append("  ")
    agent_count = f"×{summary.top_level_agent_count}"
    text.append(f"{agent_count:<{_ROW_AGENT_COUNT_WIDTH}}", style="#87D7FF")
    _append_compact_status_badge(text, summary.status_counts)
    text.append(" ")
    text.append(_saved_group_display_title(summary), style="bold")
    return text


def build_saved_group_preview(
    summary: SavedAgentGroupSummaryWire | None,
    group: SavedAgentGroupWire | None = None,
    *,
    loading: bool = False,
) -> Text:
    """Build the right-pane preview for a saved group or sentinel row."""

    preview = Text()
    if summary is None:
        preview.append("Custom revival search", style="bold #D7AFFF")
        preview.append("\n\n")
        preview.append(
            "Load the 250 most recent dismissed agents, then filter them "
            "in the next panel.",
            style="dim",
        )
        return preview

    preview.append(_saved_group_display_title(summary), style="bold #87D7FF")
    preview.append("\n")
    if summary.name and summary.name != summary.title:
        preview.append(
            _title_with_top_level_count(
                summary.title,
                summary.top_level_agent_count,
            ),
            style="dim",
        )
        preview.append("\n")
    preview.append(_saved_group_time_label(summary.created_at), style="dim")
    preview.append("\n\n")

    preview.append("Agents       ", style="bold")
    preview.append(str(summary.agent_count), style="#87D7FF")
    if summary.top_level_agent_count != summary.agent_count:
        preview.append(f" ({summary.top_level_agent_count} top-level)", style="dim")
    preview.append("\n")

    preview.append("Statuses     ", style="bold")
    _append_status_counts(preview, summary.status_counts)
    preview.append("\n")

    if summary.source == "agents_sidecar":
        preview.append("Source       ", style="bold")
        preview.append("Agents sidecar", style="dim")
        preview.append("\n")

    if summary.project_names:
        preview.append("Projects     ", style="bold")
        preview.append(_join_limited(summary.project_names), style="dim")
        preview.append("\n")

    if summary.cl_names:
        preview.append("PRs          ", style="bold")
        preview.append(_join_limited(summary.cl_names), style="dim")
        preview.append("\n")

    if summary.times_revived:
        preview.append("Revived      ", style="bold")
        preview.append(str(summary.times_revived), style="dim")
        if summary.revived_at:
            preview.append(f" | {summary.revived_at}", style="dim")
        preview.append("\n")

    if loading:
        preview.append("\nLoading group details...", style="dim italic")
        return preview

    refs = group.agent_refs if group is not None else ()
    if not refs:
        preview.append("\nSelect this group to revive it.", style="dim")
        return preview

    root_refs = tuple(ref for ref in refs if not ref.is_workflow_child)
    preview.append("\nIncluded agents", style="bold")
    preview.append("\n")
    if not root_refs:
        preview.append("  No root agent refs found\n", style="dim")
        return preview

    for idx, ref in enumerate(root_refs[:12], 1):
        _append_ref_line(preview, idx, ref)
    if len(root_refs) > 12:
        preview.append(f"  ... {len(root_refs) - 12} more root agents\n", style="dim")
    return preview


def build_load_more_preview(next_cursor: int | None) -> Text:
    """Build preview text for the load-more sentinel."""

    preview = Text()
    preview.append("Load more saved groups", style="bold #00D7AF")
    preview.append("\n\n")
    if next_cursor is None:
        preview.append("All saved groups are already loaded.", style="dim")
    else:
        preview.append(
            "Press Enter to fetch the next page before the custom search row.",
            style="dim",
        )
    return preview


def build_empty_groups_preview() -> Text:
    """Build preview text for the disabled empty-state row."""

    preview = Text()
    preview.append("No saved groups yet", style="bold")
    preview.append("\n\n")
    preview.append(
        "Use s on marked Agents-tab rows to save a group. Custom revival search "
        "is still available below.",
        style="dim",
    )
    return preview


def _saved_group_display_title(summary: SavedAgentGroupSummaryWire) -> str:
    if summary.name:
        return summary.name
    return _title_with_top_level_count(
        summary.title,
        summary.top_level_agent_count,
    )


def _title_with_top_level_count(title: str, top_level_agent_count: int) -> str:
    count_label = "agent" if top_level_agent_count == 1 else "agents"
    return _TITLE_AGENT_COUNT_RE.sub(
        f"{top_level_agent_count} {count_label}",
        title,
        count=1,
    )


def _append_ref_line(
    preview: Text,
    idx: int,
    ref: SavedAgentGroupRefWire,
) -> None:
    name = project_display_name_for(
        ref.display_name or ref.agent_name or ref.cl_name or "agent"
    )
    preview.append(f"  {idx:>2}. ", style="dim")
    preview.append(name, style="bold")
    if ref.agent_name:
        preview.append(f" @{ref.agent_name}", style="#87D7FF")
    if ref.status:
        preview.append("  ")
        preview.append(ref.status, style=_status_style(ref.status))
    runtime = _runtime_label(ref)
    if runtime:
        preview.append("  ")
        preview.append(runtime, style="dim italic")
    preview.append("\n")
    if ref.prompt_preview:
        preview.append("      prompt: ", style="dim")
        preview.append(humanize_vcs_refs_in_text(ref.prompt_preview), style="dim")
        preview.append("\n")


def _append_status_counts(text: Text, status_counts: dict[str, int]) -> None:
    if not status_counts:
        text.append("no status", style="dim")
        return
    first = True
    for status, count in sorted(status_counts.items()):
        if count <= 0:
            continue
        if not first:
            text.append(" ")
        first = False
        text.append(f"{status.lower()}:{count}", style=_status_style(status))
    if first:
        text.append("no status", style="dim")


def _row_age_label(created_at: str, *, now: datetime | None = None) -> str:
    parsed = _parse_timestamp(created_at)
    if parsed is None:
        return created_at.rjust(_ROW_AGE_WIDTH)

    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    delta_seconds = max(0, int((reference - parsed).total_seconds()))
    if delta_seconds < 60:
        relative = "now"
    elif delta_seconds < 3600:
        relative = f"{delta_seconds // 60}m"
    elif delta_seconds < 86400:
        relative = f"{delta_seconds // 3600}h"
    else:
        relative = f"{delta_seconds // 86400}d"
    return relative.rjust(_ROW_AGE_WIDTH)


def _append_compact_status_badge(
    text: Text,
    status_counts: dict[str, int],
) -> None:
    used_width = 0
    appended = False
    for status, count in _status_badge_counts(status_counts):
        token = f"{_status_glyph(status)}{count}"
        separator_width = 1 if appended else 0
        token_width = cell_len(token)
        if used_width + separator_width + token_width > _STATUS_BADGE_WIDTH:
            continue
        if appended:
            text.append(" ")
            used_width += 1
        text.append(token, style=_status_style(status))
        used_width += token_width
        appended = True

    if not appended:
        text.append("—", style="dim")
        used_width = 1

    padding = _STATUS_BADGE_WIDTH - used_width
    if padding > 0:
        text.append(" " * padding, style="dim")


def _status_badge_counts(
    status_counts: dict[str, int],
) -> tuple[tuple[str, int], ...]:
    ordered: list[tuple[str, int]] = []
    for status in _STATUS_BADGE_PRIORITY:
        count = status_counts.get(status, 0)
        if count > 0:
            ordered.append((status, count))
    for status, count in sorted(status_counts.items()):
        if status not in _STATUS_BADGE_PRIORITY and count > 0:
            ordered.append((status, count))
    return tuple(ordered)


def _status_glyph(status: str) -> str:
    return _STATUS_GLYPHS.get(status, (status[:1] or "?").upper())


def _join_limited(values: tuple[str, ...], *, limit: int = 3) -> str:
    shown = [value for value in values if value][:limit]
    if not shown:
        return ""
    suffix = "" if len(values) <= limit else f" +{len(values) - limit}"
    return ", ".join(shown) + suffix


def _runtime_label(ref: SavedAgentGroupRefWire) -> str:
    if ref.llm_provider and ref.model:
        return f"{ref.llm_provider}/{ref.model}"
    return ref.model or ref.llm_provider or ""


def _status_style(status: str) -> str:
    return f"bold {_STATUS_COLORS.get(status, '#AAAAAA')}"


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)

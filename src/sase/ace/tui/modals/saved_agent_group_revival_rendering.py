"""Rendering helpers for saved dismissed-agent group revival."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.text import Text

from sase.core.agent_group_archive_wire import (
    SavedAgentGroupRefWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
)

_STATUS_COLORS: dict[str, str] = {
    "DONE": "#5FD75F",
    "FAILED": "#FF5F5F",
    "WAITING INPUT": "#FF87D7",
    "RUNNING": "#87AFFF",
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


def _saved_group_row_time_label(
    created_at: str,
    *,
    now: datetime | None = None,
) -> str:
    """Return a short saved-time label for list rows."""

    parsed = _parse_timestamp(created_at)
    if parsed is None:
        return created_at

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
    return f"{relative} | {parsed.strftime('%m-%d %H:%M')}"


def format_saved_group_row(
    summary: SavedAgentGroupSummaryWire,
    index: int,
    *,
    now: datetime | None = None,
    source_label: str | None = None,
) -> Text:
    """Build one saved-group list row."""

    text = Text()
    text.append(f"{index + 1:>2}. ", style="dim")
    if summary.revived_at:
        text.append("revived ", style="dim italic")
    text.append(_saved_group_display_title(summary), style="bold")
    if summary.name and summary.name != summary.title:
        text.append("  ")
        text.append(summary.title, style="dim")
    text.append("  ")
    text.append(_saved_group_row_time_label(summary.created_at, now=now), style="dim")
    if source_label:
        text.append("  ")
        text.append(source_label, style="dim italic")
    text.append("  ")
    text.append(f"{summary.agent_count} agents", style="#87D7FF")
    text.append("  ")
    _append_status_counts(text, summary.status_counts)

    hints = _compact_hints(summary)
    if hints:
        text.append("  ")
        text.append(hints, style="dim")
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
            "Open the existing project/CL scoped dismissed-agent search.",
            style="dim",
        )
        return preview

    preview.append(_saved_group_display_title(summary), style="bold #87D7FF")
    preview.append("\n")
    if summary.name and summary.name != summary.title:
        preview.append(summary.title, style="dim")
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

    if summary.project_names:
        preview.append("Projects     ", style="bold")
        preview.append(_join_limited(summary.project_names), style="dim")
        preview.append("\n")

    if summary.cl_names:
        preview.append("CLs          ", style="bold")
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

    preview.append("\nIncluded agents", style="bold")
    preview.append("\n")
    for idx, ref in enumerate(refs[:12], 1):
        _append_ref_line(preview, idx, ref)
    if len(refs) > 12:
        preview.append(f"  ... {len(refs) - 12} more\n", style="dim")
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
    return summary.name or summary.title


def _append_ref_line(
    preview: Text,
    idx: int,
    ref: SavedAgentGroupRefWire,
) -> None:
    name = ref.display_name or ref.agent_name or ref.cl_name or "agent"
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


def _compact_hints(summary: SavedAgentGroupSummaryWire) -> str:
    hints: list[str] = []
    if summary.cl_names:
        hints.append(_join_limited(summary.cl_names, limit=2))
    elif summary.project_names:
        hints.append(_join_limited(summary.project_names, limit=2))
    if summary.times_revived:
        hints.append(f"revived x{summary.times_revived}")
    return " | ".join(hints)


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

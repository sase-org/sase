"""Row rendering helpers for the ACE Episode Explorer modal."""

from __future__ import annotations

from rich.text import Text

from sase.memory.episodes._collector_utils import compact_timestamp
from sase.memory.episodes.inventory import EpisodeInventoryItem

from .episode_explorer_filters import EpisodeExplorerDisplayRow


def row_text(row: EpisodeExplorerDisplayRow) -> Text:
    text = Text(no_wrap=True)
    item = row.item
    if row.is_alias:
        text.append("alias ", style="bold #D7AF5F")
        text.append(_short(row.display_episode_id, 28), style="bold #87D7FF")
        text.append(" -> ", style="dim")
        text.append(_short(row.canonical_episode_id, 28), style="bold")
        if row.alias_reason:
            text.append(f"  {row.alias_reason}", style="dim")
        text.append("\n")
        text.append(f"  {_short(item.row.title, 76)}", style="dim")
        return text
    row_data = item.row
    text.append(_time_span(row_data.first_event_at, row_data.last_event_at))
    text.append(f"  {row_data.importance_band}", style="bold #D7AF5F")
    text.append(f"  {row_data.status}", style="dim")
    text.append(f"  {item.version}", style="dim #87D7FF")
    if item.warnings:
        text.append(f"  warnings={len(item.warnings)}", style="bold red")
    text.append("\n")
    text.append(f"  {_short(row_data.episode_id, 24)}", style="bold #87D7FF")
    text.append(f"  {_short(row_data.title, 58)}")
    details = _row_details(item)
    if details:
        text.append(f"\n  {_short(details, 86)}", style="dim")
    return text


def _row_details(item: EpisodeInventoryItem) -> str:
    row = item.row
    parts = []
    if row.root_agent_names:
        parts.append("agents=" + ",".join(row.root_agent_names))
    if row.changespec_name:
        parts.append(f"cl={row.changespec_name}")
    if row.bead_ids:
        parts.append("beads=" + ",".join(row.bead_ids))
    parts.append(f"sources={row.source_count}")
    if item.aliases:
        parts.append(f"aliases={len(item.aliases)}")
    return "  ".join(parts)


def _time_span(first: str | None, last: str | None) -> str:
    start = _format_timestamp(first)
    end = _format_timestamp(last)
    if start and end and start != end:
        return f"{start}..{end}"
    return start or end or "undated"


def _format_timestamp(value: str | None) -> str:
    if not value:
        return ""
    compact = compact_timestamp(value)
    if len(compact) >= 12 and compact[:12].isdigit():
        return (
            f"{compact[:4]}-{compact[4:6]}-{compact[6:8]} "
            f"{compact[8:10]}:{compact[10:12]}"
        )
    if len(compact) >= 8 and compact[:8].isdigit():
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
    return value


def _short(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


__all__ = [
    "row_text",
]

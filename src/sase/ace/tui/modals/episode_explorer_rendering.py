"""Rendering helpers for the Episode Explorer modal."""

from __future__ import annotations

from rich.text import Text

from sase.core.episode_wire import EpisodeSourceRefWire, EpisodeWire
from sase.memory.episodes._collector_utils import compact_timestamp
from sase.memory.episodes.inventory import EpisodeInventoryItem
from sase.memory.episodes.render import (
    render_agent_text,
    render_graph_text,
    render_overview_text,
    render_sources_text,
    render_timeline_text,
)

from .episode_explorer_types import (
    EpisodeExplorerEdgeMode,
    EpisodeExplorerView,
    EpisodeExplorerDisplayRow,
)


def detail_text(
    row: EpisodeExplorerDisplayRow,
    episode: EpisodeWire,
    *,
    view: EpisodeExplorerView,
    edge_mode: EpisodeExplorerEdgeMode,
    verify_status: str,
    width: int,
    current_source: EpisodeSourceRefWire | None = None,
) -> str:
    alias_line = (
        f"Alias: {row.display_episode_id} -> {row.canonical_episode_id}\n"
        if row.is_alias
        else ""
    )
    source_line = ""
    if view == "sources" and current_source is not None:
        source_line = f"Source cursor: {current_source.id} {current_source.path}\n"
    header = (
        f"View: {view}"
        f"{' (' + edge_mode + ')' if view == 'graph' else ''}\n"
        f"Verification: {verify_status}\n"
        f"{alias_line}"
        f"{source_line}\n"
    )
    if view == "overview":
        body = render_overview_text(episode, width=width)
    elif view == "timeline":
        body = render_timeline_text(episode, width=width)
    elif view == "graph":
        body = render_graph_text(episode, edge_mode=edge_mode, width=width)
    elif view == "sources":
        body = render_sources_text(episode, width=width)
    else:
        body = render_agent_text(episode, width=width)
    return header + body


def row_text(row: EpisodeExplorerDisplayRow) -> Text:
    text = Text(no_wrap=True)
    item = row.item
    if row.is_alias:
        text.append("alias ", style="bold #D7AF5F")
        text.append(short(row.display_episode_id, 28), style="bold #87D7FF")
        text.append(" -> ", style="dim")
        text.append(short(row.canonical_episode_id, 28), style="bold")
        if row.alias_reason:
            text.append(f"  {row.alias_reason}", style="dim")
        text.append("\n")
        text.append(f"  {short(item.row.title, 76)}", style="dim")
        return text
    row_data = item.row
    text.append(time_span(row_data.first_event_at, row_data.last_event_at))
    text.append(f"  {row_data.importance_band}", style="bold #D7AF5F")
    text.append(f"  {row_data.status}", style="dim")
    text.append(f"  {item.version}", style="dim #87D7FF")
    if item.warnings:
        text.append(f"  warnings={len(item.warnings)}", style="bold red")
    text.append("\n")
    text.append(f"  {short(row_data.episode_id, 24)}", style="bold #87D7FF")
    text.append(f"  {short(row_data.title, 58)}")
    details = row_details(item)
    if details:
        text.append(f"\n  {short(details, 86)}", style="dim")
    return text


def row_details(item: EpisodeInventoryItem) -> str:
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


def time_span(first: str | None, last: str | None) -> str:
    start = format_timestamp(first)
    end = format_timestamp(last)
    if start and end and start != end:
        return f"{start}..{end}"
    return start or end or "undated"


def format_timestamp(value: str | None) -> str:
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


def short(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


__all__ = [
    "detail_text",
    "format_timestamp",
    "row_details",
    "row_text",
    "short",
    "time_span",
]

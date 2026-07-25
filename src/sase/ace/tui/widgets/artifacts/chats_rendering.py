"""Pure Rich renderable builders for the Artifacts Chats pane."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.keymaps import KeymapRegistry, key_display_name
from sase.core.agent_identity_facade import present_agent_name
from sase.history.chat_catalog_provenance import (
    CHAT_PROVENANCE_VALUES,
    ChatCatalogEntry,
    ChatCatalogSnapshot,
    ChatProvenance,
)
from sase.history.chat_filter_query import ChatFilterValues, to_query_tokens

from .types import ARTIFACTS_ACCENTS


CHAT_PROVENANCE_GLYPHS: dict[ChatProvenance, str] = {
    "local": "◇",
    "shared": "◆",
    "remote": "⇣",
    "unknown": "◌",
}
CHAT_PROVENANCE_COLORS: dict[ChatProvenance, str] = {
    "local": "#767676",
    "shared": "#5FD75F",
    "remote": "#FFAF5F",
    "unknown": "#585858",
}
_BADGE_WIDTH = 10


def _build_chats_scope(
    registry: KeymapRegistry,
    *,
    project_scope: str | None,
    project_display_name: str | None,
) -> Text:
    """Build the pane's project-scope header."""

    accent = ARTIFACTS_ACCENTS["chats"]
    scope = project_display_name or project_scope or "All projects"
    text = Text()
    text.append(" Chats ", style=f"bold #1a1a1a on {accent}")
    text.append("  Project scope  ", style="dim")
    text.append(f" {scope} ", style=f"bold {accent}")
    text.append("  ·  ", style="dim")
    text.append(
        f"{key_display_name(registry.app.pick_artifacts_project)} change",
        style="dim",
    )
    return text


def build_chats_info(
    registry: KeymapRegistry,
    snapshot: ChatCatalogSnapshot | None,
    *,
    project_scope: str | None,
    project_display_name: str | None,
    filters: ChatFilterValues,
) -> Text:
    """Build project scope, provenance summary chips, and committed filters."""

    text = _build_chats_scope(
        registry,
        project_scope=project_scope,
        project_display_name=project_display_name,
    )
    if snapshot is not None:
        text.append("  │  ", style="dim")
        active = filters.provenances[0] if len(filters.provenances) == 1 else None
        for index, provenance in enumerate(CHAT_PROVENANCE_VALUES):
            if index:
                text.append(" · ", style="dim")
            count = snapshot.provenance_counts.get(provenance, 0)
            glyph = CHAT_PROVENANCE_GLYPHS[provenance]
            label: str = provenance
            if provenance == "remote":
                machine_count = len(snapshot.remote_machines)
                suffix = "machine" if machine_count == 1 else "machines"
                label = f"remote ({machine_count} {suffix})"
            style = f"bold {CHAT_PROVENANCE_COLORS[provenance]}"
            if active is not None and provenance != active:
                style = f"dim {CHAT_PROVENANCE_COLORS[provenance]}"
            elif active == provenance:
                style += " reverse"
            text.append(f"{glyph} {count:,} {label}", style=style)
    tokens = to_query_tokens(filters)
    if tokens:
        text.append("  │  ", style="dim")
        text.append(" ".join(tokens), style=f"bold {ARTIFACTS_ACCENTS['chats']}")
    return text


def build_chats_status(
    snapshot: ChatCatalogSnapshot | None,
    *,
    loading: bool,
    load_error: str | None,
    extending: bool,
) -> Text:
    """Build loading state and compact provenance totals."""

    text = Text()
    if load_error:
        text.append(load_error, style="bold #FF5F5F")
        return text
    if snapshot is None:
        text.append(
            "Loading chat transcripts…" if loading else "Chats have not loaded yet",
            style="bold #FFD700" if loading else "dim",
        )
        return text

    text.append(f"{len(snapshot.entries):,} transcripts loaded", style="dim")
    if extending:
        text.append("  ·  Loading full history…", style="dim #FFD700")
    return text


def build_chats_hints(
    registry: KeymapRegistry,
    *,
    has_agent: bool = True,
) -> Text:
    """Build the phase-owned action hints shown below the panels."""

    keymap = registry.app
    parts = (
        (key_display_name(keymap.chats_next), "next"),
        (key_display_name(keymap.chats_prev), "prev"),
        (key_display_name(keymap.chats_view_selected), "view"),
        (key_display_name(keymap.edit_query), "filter"),
        (key_display_name(keymap.chats_cycle_provenance), "sync"),
        (key_display_name(keymap.chats_open_agent), "agent"),
        (key_display_name(keymap.chats_open_external), "editor"),
        (key_display_name(keymap.chats_copy_path), "copy path"),
        (key_display_name(keymap.chats_refresh), "refresh"),
    )
    text = Text(justify="center")
    for index, (key, label) in enumerate(parts):
        if index:
            text.append("  ·  ", style="dim")
        disabled = label == "agent" and not has_agent
        text.append(
            key,
            style=("dim" if disabled else f"bold {ARTIFACTS_ACCENTS['chats']}"),
        )
        text.append(f" {label}", style="dim")
    return text


def chat_group_label(entry: ChatCatalogEntry, *, today: datetime) -> str:
    """Return Today, Yesterday, or an ISO date for one catalog entry."""

    timestamp = _chat_datetime(entry)
    if timestamp is None:
        return "Unknown"
    day_delta = (today.date() - timestamp.date()).days
    if day_delta == 0:
        return "Today"
    if day_delta == 1:
        return "Yesterday"
    return timestamp.date().isoformat()


def _chat_datetime(entry: ChatCatalogEntry) -> datetime | None:
    """Parse the catalog's local ISO mtime without doing any disk work."""

    try:
        return datetime.fromisoformat(entry.mtime)
    except ValueError:
        return None


def chat_row_text(entry: ChatCatalogEntry) -> Text:
    """Render one compact, provenance-striped chat row."""

    provenance = entry.provenance
    color = CHAT_PROVENANCE_COLORS[provenance]
    glyph = CHAT_PROVENANCE_GLYPHS[provenance]
    label = _provenance_label(entry)
    timestamp = _chat_datetime(entry)
    time_label = timestamp.strftime("%H:%M") if timestamp is not None else "--:--"
    project = entry.project_key or "local"
    agent = entry.agent_local_name or entry.agent
    presented = present_agent_name(agent) if agent else (entry.workflow or "chat")
    snippet = entry.prompt_snippet or entry.response_snippet or entry.basename

    text = Text(no_wrap=True, overflow="ellipsis")
    text.append("▌", style=f"bold {color}")
    text.append(f"{glyph} {label}".ljust(_BADGE_WIDTH), style=f"bold {color}")
    text.append(f"  {time_label}  ", style="dim")
    text.append(f"[{project}]".ljust(10), style=f"bold {ARTIFACTS_ACCENTS['chats']}")
    text.append(f"  {presented}", style="bold white")
    text.append(f"  {snippet}", style="dim")
    return text


def chat_group_header(label: str) -> Text:
    """Render a disabled date separator."""

    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f"── {label} ", style="dim")
    text.append("─" * 20, style="dim #5F5F87")
    return text


def _provenance_label(entry: ChatCatalogEntry) -> str:
    if entry.provenance == "remote":
        return entry.source_machine or "remote"
    if entry.provenance == "unknown":
        return "?"
    return entry.provenance


__all__ = [
    "CHAT_PROVENANCE_COLORS",
    "CHAT_PROVENANCE_GLYPHS",
    "build_chats_hints",
    "build_chats_info",
    "build_chats_status",
    "chat_group_header",
    "chat_group_label",
    "chat_row_text",
]

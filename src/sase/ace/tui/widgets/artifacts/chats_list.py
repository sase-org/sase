"""Grouped OptionList construction for the Artifacts Chats pane."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from textual.widgets.option_list import Option

from sase.history.chat_catalog_provenance import ChatCatalogEntry

from .chats_data import ChatsSnapshot
from .chats_rendering import (
    chat_group_header,
    chat_group_label,
    chat_row_text,
)
from .entry_navigation import (
    ArtifactEntryTarget,
    prepend_jump_hint,
    prepend_mark_glyph,
)


@dataclass(frozen=True, slots=True)
class ChatRow:
    """Identity-preserving row backing one selectable chat option."""

    option_id: str
    entry: ChatCatalogEntry


def chat_row_target(row: ChatRow) -> ArtifactEntryTarget:
    """Use the absolute transcript path as the stable navigation identity."""

    return ("chat", row.entry.absolute_path)


def build_chat_options(
    snapshot: ChatsSnapshot | None,
    *,
    project_scope: str | None,
    loading: bool,
    now: datetime,
    jump_hints: Mapping[ArtifactEntryTarget, str] | None = None,
    marks: set[ArtifactEntryTarget] | None = None,
) -> tuple[list[Option], dict[str, ChatRow]]:
    """Build newest-first date groups and their selectable row map."""

    active_marks = marks or set()
    if snapshot is None or snapshot.project != project_scope:
        label = "Loading chats…" if loading else "Chats have not loaded yet."
        return [Option(label, disabled=True)], {}
    if not snapshot.entries:
        return [], {}

    options: list[Option] = []
    rows: dict[str, ChatRow] = {}
    current_group: str | None = None
    for entry in snapshot.entries:
        group = chat_group_label(entry, today=now)
        if group != current_group:
            options.append(
                Option(
                    chat_group_header(group),
                    id=f"header:{group.casefold()}",
                    disabled=True,
                )
            )
            current_group = group
        option_id = _chat_option_id(entry.absolute_path)
        row = ChatRow(option_id, entry)
        rows[option_id] = row
        options.append(
            Option(
                prepend_jump_hint(
                    prepend_mark_glyph(
                        chat_row_text(entry),
                        chat_row_target(row) in active_marks,
                    ),
                    (jump_hints or {}).get(chat_row_target(row)),
                ),
                id=option_id,
            )
        )
    return options, rows


def _chat_option_id(absolute_path: str) -> str:
    digest = sha256(absolute_path.encode("utf-8")).hexdigest()[:20]
    return f"chat:{digest}"


__all__ = ["ChatRow", "build_chat_options", "chat_row_target"]

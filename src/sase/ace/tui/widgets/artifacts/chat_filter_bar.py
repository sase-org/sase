"""Inline query editor and completion menu for Artifacts Chats."""

from __future__ import annotations

from collections.abc import Iterable

from textual.message import Message

from sase.ace.tui.widgets.filter_bar import FilterBar
from sase.history.chat_filter_query import chat_completion_context

from .types import ARTIFACTS_ACCENTS

_DATE_COMPLETIONS = (
    "1h",
    "24h",
    "today",
    "yesterday",
    "3d",
    "7d",
    "2w",
    "YYYY-MM-DD",
)


class ChatFilterBar(FilterBar):
    """Slash-style Chats filter editor with catalog-backed completion."""

    ACCENT = ARTIFACTS_ACCENTS["chats"]
    ROW_ID = "chat-filter-row"
    SIGIL_ID = "chat-filter-sigil"
    INPUT_ID = "chat-filter-input"
    STATUS_ID = "chat-filter-status"
    COMPLETION_ID = "chat-filter-completion"
    CANDIDATE_ID_PREFIX = "chat-filter-candidate"
    KEY_COMPLETIONS = (
        ("provenance", "local, shared, remote, unknown"),
        ("machine", "source machine"),
        ("project", "project key"),
        ("agent", "agent name"),
        ("workflow", "workflow name"),
        ("since", "Nh/Nd/Nw, today, YYYY-MM-DD"),
        ("until", "Nh/Nd/Nw, today, YYYY-MM-DD"),
    )
    STATIC_VALUE_COMPLETIONS = {
        "provenance": ("local", "shared", "remote", "unknown"),
        "since": _DATE_COMPLETIONS,
        "until": _DATE_COMPLETIONS,
    }
    VALUE_HINTS = {
        "provenance": "sync provenance",
        "machine": "source machine",
        "project": "project",
        "agent": "agent",
        "workflow": "workflow",
        "since": "date bound",
        "until": "date bound",
    }
    REPEATABLE_VALUE_KINDS = frozenset(
        ("provenance", "machine", "project", "agent", "workflow")
    )
    FREE_TEXT_HINT = "basename, agent, workflow, snippets (AND)"

    class QueryChanged(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Dismissed(Message):
        pass

    def set_completion_sources(
        self,
        *,
        machines: Iterable[str],
        projects: Iterable[str],
        agents: Iterable[str],
        workflows: Iterable[str],
    ) -> None:
        self._set_completion_sources(
            {
                "machine": machines,
                "project": projects,
                "agent": agents,
                "workflow": workflows,
            }
        )

    def _completion_context(
        self,
        text: str,
        cursor: int,
    ) -> tuple[str, str, bool]:
        return chat_completion_context(text, cursor)


__all__ = ["ChatFilterBar"]

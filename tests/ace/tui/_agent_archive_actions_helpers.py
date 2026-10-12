"""Shared setup for the split Archive action tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_view import init_agents_archive_view_state
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    ARCHIVE_SECTION_LIST,
)


def make_owner(*, inbox_agent: Any = None) -> SimpleNamespace:
    owner = SimpleNamespace()
    owner.current_tab = "agents"
    owner.current_idx = 0
    owner.notices: list[tuple[str, Any]] = []
    owner._marked_agents = set()
    owner._unread_completed_agent_ids = {"some:live:identity"}
    owner._inbox_agent = inbox_agent

    def notify(message: str, *, severity: str = "information") -> None:
        owner.notices.append((message, severity))

    def get_selected_agent() -> Any:
        return owner._inbox_agent

    owner.notify = notify
    owner._get_selected_agent = get_selected_agent
    init_agents_archive_view_state(owner)
    return owner


def open_archive(
    owner: SimpleNamespace, *, selected_key: str | None = "u.m@r1"
) -> None:
    owner._agents_archive_view.active_view = AGENTS_VIEW_ARCHIVE
    owner._agents_archive_view.generation += 1
    owner._agents_archive_view.archive.selected_key = selected_key
    owner._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_LIST


__all__ = ["make_owner", "open_archive"]

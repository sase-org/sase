"""Shared setup for the split Archive restore, fork, and copy tests.

Public helpers used by more than one split module live here under public
names so no new module imports a ``_``-prefixed name from another new
module.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_view import init_agents_archive_view_state
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    ARCHIVE_SECTION_LIST,
)

__all__ = [
    "make_agent",
    "make_owner",
    "make_row",
    "open_archive",
    "wire_bundles",
]


def make_agent(name: str = "bob-cli-5p.4", **overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "agent_name": name,
        "presented_agent_name": name,
        "display_name": name,
        "cl_name": name,
        "status": "DONE",
        "identity": ("agent", name, None),
        "durably_revivable": True,
        "raw_suffix": "suffix-1",
        "response_path": "/tmp/chat.md",
        "artifacts_dir": "/tmp/artifacts",
        "is_clan_container": False,
        "is_agent_entry": True,
        "is_agent_session_container_row": False,
        "is_workflow_step_child": False,
        "project_display_name": "Test",
        "model": "muse",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def make_row(name: str = "bob-cli-5p.4", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"agent_name": name, "restorable": True}
    row.update(overrides)
    return row


def make_owner() -> SimpleNamespace:
    owner = SimpleNamespace()
    owner.current_tab = "agents"
    owner.notices: list[tuple[str, Any]] = []
    owner.pushed: list[tuple[Any, Any]] = []
    owner._marked_agents = set()

    def notify(message: str, *, severity: str = "information") -> None:
        owner.notices.append((message, severity))

    def push_screen(modal: Any, callback: Any = None) -> None:
        owner.pushed.append((modal, callback))

    owner.notify = notify
    owner.push_screen = push_screen
    init_agents_archive_view_state(owner)
    return owner


def open_archive(
    owner: SimpleNamespace, *, selected_key: str | None = "u.m@r1"
) -> None:
    owner._agents_archive_view.active_view = AGENTS_VIEW_ARCHIVE
    owner._agents_archive_view.generation += 1
    owner._agents_archive_view.archive.selected_key = selected_key
    owner._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_LIST


def wire_bundles(
    monkeypatch: Any,
    owner: SimpleNamespace,
    bundles: dict[str, tuple[dict[str, Any], SimpleNamespace | None, bool]],
) -> None:
    """Map archive key -> (light row, hydrated agent, unreadable)."""
    import sase.ace.tui.actions.agents._archive_column as column
    import sase.ace.tui.actions.agents._archive_reader as reader

    rows = {key: row for key, (row, _agent, _bad) in bundles.items()}
    monkeypatch.setattr(column, "archive_light_row", lambda _o, k: rows.get(k))
    monkeypatch.setattr(column, "archive_container_members", lambda _o, _c: ())

    def _bundle(_o: Any, light_row: Any) -> dict[str, Any]:
        for _key, (row, agent, bad) in bundles.items():
            if row is light_row:
                return {
                    "unreadable": bad,
                    "path": "/tmp/bundle.json",
                    "agent": None if bad else agent,
                    "retained": (),
                    "missing": (),
                }
        return {"unreadable": True, "path": None, "agent": None}

    monkeypatch.setattr(reader, "_load_archive_bundle", _bundle)

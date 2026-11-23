"""Shared Archive-controller helpers.

Support seam for the Archive controller split. ``controller``,
``view_state``, ``active_view``, and ``ARCHIVE_TASK_REGISTRY`` are
deliberately public names inside this already-private module so the split
controller modules can share them without importing a ``_``-prefixed name
across modules. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_controller`, which does not
re-export these helpers.
"""

from __future__ import annotations

from typing import Any

from ...models.agent_archive_controller import (
    AgentsArchiveControllerState,
    startup_agents_archive_controller_state,
)
from ...models.agent_archive_view import AGENTS_VIEW_INBOX

ARCHIVE_TASK_REGISTRY = "_archive_controller_tasks"

__all__ = [
    "ARCHIVE_TASK_REGISTRY",
    "active_view",
    "controller",
    "view_state",
]


def controller(owner: Any) -> AgentsArchiveControllerState:
    state = getattr(owner, "_agents_archive_controller", None)
    if isinstance(state, AgentsArchiveControllerState):
        return state
    state = startup_agents_archive_controller_state()
    owner._agents_archive_controller = state
    return state


def view_state(owner: Any) -> Any:
    return getattr(owner, "_agents_archive_view", None)


def active_view(owner: Any) -> str:
    view = view_state(owner)
    active = getattr(view, "active_view", None)
    return str(active) if active else AGENTS_VIEW_INBOX

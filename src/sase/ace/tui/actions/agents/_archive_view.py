"""Agents-tab Archive view lifecycle, selection, and detail-ownership guards.

Public facade for the split view-foundation modules. Behavior lives in
:mod:`sase.ace.tui.actions.agents._archive_view_state` (view state and
detail ownership), ``_archive_view_parking`` (deck and scroll parking),
``_archive_view_lifecycle`` (open/close), and ``_archive_view_selection``
(view-aware selection and key routing). This module re-exports the public
names only so every existing import path keeps working.
"""

from __future__ import annotations

from ._archive_view_lifecycle import (
    close_agents_archive_view,
    mark_archive_row_restored,
    open_agents_archive_view,
    open_agents_archive_view_with_query,
)
from ._archive_view_parking import flush_pending_archive_list_scroll
from ._archive_view_selection import (
    archive_read_only_context,
    get_agents_tab_selection,
    route_archive_key,
)
from ._archive_view_state import (
    agents_archive_view_state,
    agents_inbox_detail_allowed,
    archive_detail_owns_panel,
    cancel_inbox_detail_debounce,
    init_agents_archive_view_state,
    remember_agents_detail_owner,
    schedule_owned_inbox_detail_update,
    scheduled_agents_detail_is_current,
)

__all__ = [
    "route_archive_key",
    "agents_archive_view_state",
    "archive_detail_owns_panel",
    "archive_read_only_context",
    "agents_inbox_detail_allowed",
    "cancel_inbox_detail_debounce",
    "close_agents_archive_view",
    "flush_pending_archive_list_scroll",
    "get_agents_tab_selection",
    "init_agents_archive_view_state",
    "mark_archive_row_restored",
    "open_agents_archive_view",
    "open_agents_archive_view_with_query",
    "remember_agents_detail_owner",
    "schedule_owned_inbox_detail_update",
    "scheduled_agents_detail_is_current",
]

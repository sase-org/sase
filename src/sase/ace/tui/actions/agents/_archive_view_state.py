"""Agents-tab Archive view state and detail-ownership guards.

View-foundation seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
``owner`` is the app, duck-typed so fakes can drive every helper without a
composed widget tree. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_view`, which re-exports this
module's public names.
"""

from __future__ import annotations

import logging
from typing import Any

from ...models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AgentsArchiveViewState,
    DetailOwnership,
    capture_detail_owner,
    detail_owner_is_current,
    startup_agents_archive_view_state,
)

log = logging.getLogger(__name__)


def _view_state(owner: Any) -> AgentsArchiveViewState:
    """Return the owner's view state, lazily starting up in the Inbox."""
    state = getattr(owner, "_agents_archive_view", None)
    if state is None:
        state = startup_agents_archive_view_state()
        owner._agents_archive_view = state
    return state


def agents_archive_view_state(owner: Any) -> AgentsArchiveViewState:
    """Return the owner's Archive/Inbox view state (public consumer seam).

    Action-boundary consumers (marks, footer, guards) read parked state
    through here instead of the private ``_view_state`` so the
    view-foundation contract stays import-clean.
    """
    return _view_state(owner)


def init_agents_archive_view_state(owner: Any) -> AgentsArchiveViewState:
    """Initialize lifecycle state. Startup is always Inbox."""
    state = startup_agents_archive_view_state()
    try:
        from ....grouping_strategy import load_agent_archive_grouping

        state.archive.grouping = load_agent_archive_grouping()
    except Exception:
        log.debug("could not load Archive grouping preference", exc_info=True)
    owner._agents_archive_view = state
    owner._agents_detail_scheduled_owner = None
    from ._archive_controller import init_agents_archive_controller

    init_agents_archive_controller(owner)
    return state


def _agents_view_is_archive(owner: Any) -> bool:
    """Return whether the Agents tab is parked in the Archive view."""
    return _view_state(owner).active_view == AGENTS_VIEW_ARCHIVE


def archive_detail_owns_panel(owner: Any) -> bool:
    """Return whether the Archive owns the shared detail panel."""
    return _agents_view_is_archive(owner)


def agents_inbox_detail_allowed(owner: Any) -> bool:
    """Return whether Inbox-originated detail rendering may paint."""
    return not archive_detail_owns_panel(owner)


def _selection_key_for(owner: Any, state: AgentsArchiveViewState) -> str | None:
    """Return the stable key identifying the current selection in its view."""
    if state.active_view == AGENTS_VIEW_ARCHIVE:
        return state.archive.selected_key
    selector = getattr(owner, "_get_selected_agent", None)
    agent = selector() if callable(selector) else None
    identity = getattr(agent, "identity", None)
    return None if identity is None else str(identity)


def _capture_agents_detail_owner(owner: Any) -> DetailOwnership:
    """Capture the render token for the current view and selection."""
    state = _view_state(owner)
    return capture_detail_owner(
        view=state.active_view,
        generation=state.generation,
        selection_key=_selection_key_for(owner, state),
    )


def remember_agents_detail_owner(owner: Any) -> DetailOwnership:
    """Capture and record the token for a scheduled debounced update."""
    token = _capture_agents_detail_owner(owner)
    owner._agents_detail_scheduled_owner = token
    return token


def schedule_owned_inbox_detail_update(owner: Any) -> None:
    """Record a fresh owner token, then schedule the shared detail debouncer.

    Every Inbox schedule of ``_fire_debounced_detail_update`` funnels through
    here so the fire's currency check sees the token from the latest schedule
    instead of a stale token left behind by an Archive round trip. Callers
    must check :func:`agents_inbox_detail_allowed` first: scheduling while
    the Archive owns the panel would replace its pending hydration callback
    on the shared debouncer.
    """
    remember_agents_detail_owner(owner)
    owner._agent_detail_debouncer.schedule(owner._fire_debounced_detail_update)


def scheduled_agents_detail_is_current(owner: Any) -> bool:
    """Return whether the pending debounced update still owns the panel."""
    token = getattr(owner, "_agents_detail_scheduled_owner", None)
    scheduled = token if isinstance(token, DetailOwnership) else None
    state = _view_state(owner)
    return detail_owner_is_current(
        scheduled,
        view=state.active_view,
        generation=state.generation,
    )


def cancel_inbox_detail_debounce(owner: Any) -> bool:
    """Cancel the pending debounced detail unless the Archive owns the panel.

    A hidden Inbox refresh must never cancel the Archive's pending debounce.
    Returns True when the debounce was actually cancelled.
    """
    if archive_detail_owns_panel(owner):
        return False
    debouncer = getattr(owner, "_agent_detail_debouncer", None)
    cancel = getattr(debouncer, "cancel", None)
    if not callable(cancel):
        return False
    cancel()
    return True


__all__ = [
    "agents_archive_view_state",
    "agents_inbox_detail_allowed",
    "archive_detail_owns_panel",
    "cancel_inbox_detail_debounce",
    "init_agents_archive_view_state",
    "remember_agents_detail_owner",
    "schedule_owned_inbox_detail_update",
    "scheduled_agents_detail_is_current",
]

"""Agents-tab Archive view lifecycle, selection, and detail-ownership guards.

View-foundation seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
``owner`` is the app, duck-typed so fakes can drive every helper without a
composed widget tree. ``_get_selected_agent`` keeps its Inbox-only semantics;
read callers opt into :func:`get_agents_tab_selection` instead.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ...models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_NONE,
    ARCHIVE_STATUS_ALREADY_INBOX,
    ARCHIVE_STATUS_ALREADY_OPEN,
    ARCHIVE_STATUS_DISABLED,
    ARCHIVE_STATUS_OPENED,
    ARCHIVE_STATUS_RETURNED,
    AgentsArchiveViewState,
    AgentsTabSelection,
    ArchiveViewOutcome,
    ArchiveViewState,
    DetailOwnership,
    ParkedInboxState,
    ReadOnlyArchiveContext,
    agents_archive_view_enabled,
    capture_detail_owner,
    detail_owner_is_current,
    startup_agents_archive_view_state,
)


def _view_state(owner: Any) -> AgentsArchiveViewState:
    """Return the owner's view state, lazily starting up in the Inbox."""
    state = getattr(owner, "_agents_archive_view", None)
    if state is None:
        state = startup_agents_archive_view_state()
        owner._agents_archive_view = state
    return state


def init_agents_archive_view_state(owner: Any) -> AgentsArchiveViewState:
    """Initialize lifecycle state. Startup is always Inbox."""
    state = startup_agents_archive_view_state()
    owner._agents_archive_view = state
    owner._agents_detail_scheduled_owner = None
    from ._archive_controller import init_agents_archive_controller

    init_agents_archive_controller(owner)
    return state


def agents_view_is_archive(owner: Any) -> bool:
    """Return whether the Agents tab is parked in the Archive view."""
    return _view_state(owner).active_view == AGENTS_VIEW_ARCHIVE


def archive_detail_owns_panel(owner: Any) -> bool:
    """Return whether the Archive owns the shared detail panel.

    With the beta off this is always False, so Inbox rendering stays
    byte-identical to today.
    """
    return agents_archive_view_enabled() and agents_view_is_archive(owner)


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


def capture_agents_detail_owner(owner: Any) -> DetailOwnership:
    """Capture the render token for the current view and selection."""
    state = _view_state(owner)
    return capture_detail_owner(
        view=state.active_view,
        generation=state.generation,
        selection_key=_selection_key_for(owner, state),
    )


def remember_agents_detail_owner(owner: Any) -> DetailOwnership:
    """Capture and record the token for a scheduled debounced update."""
    token = capture_agents_detail_owner(owner)
    owner._agents_detail_scheduled_owner = token
    return token


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


def invalidate_agents_detail_ownership(owner: Any) -> int:
    """Invalidate earlier detail work. Returns the new generation.

    Lifecycle teardown primitive: every view switch funnels through here so
    workers started before the switch (debounced updates, async headers,
    hydration) drop instead of repainting a panel they no longer own. The
    recorded scheduled token is deliberately left in place: it now disagrees
    with the bumped generation, so the pending fire drops as stale.
    """
    state = _view_state(owner)
    state.generation += 1
    return state.generation


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


def _capture_parked_inbox(owner: Any) -> ParkedInboxState:
    """Snapshot the Inbox state parked while the Archive is active."""
    selector = getattr(owner, "_get_selected_agent", None)
    agent = selector() if callable(selector) else None
    return ParkedInboxState(
        committed_query=str(getattr(owner, "_agent_search_query", "") or ""),
        selected_identity=getattr(agent, "identity", None),
        scroll=int(getattr(owner, "current_idx", 0) or 0),
        agent_tab=getattr(owner, "_agents_current_tab", None),
        panel_focus=None,
        deck_choices={},
        folds=(),
    )


def open_agents_archive_view(owner: Any) -> ArchiveViewOutcome:
    """Open the Archive with its parked state (the pure ``,a`` toggle seam).

    Consumed by the query-parking phase; later phases add list hydration.
    """
    if not agents_archive_view_enabled():
        state = _view_state(owner)
        return ArchiveViewOutcome(
            status=ARCHIVE_STATUS_DISABLED,
            view=state.active_view,
            generation=state.generation,
        )
    state = _view_state(owner)
    if state.active_view == AGENTS_VIEW_ARCHIVE:
        from ._archive_controller import request_archive_view_load

        request_archive_view_load(owner)
        return ArchiveViewOutcome(
            status=ARCHIVE_STATUS_ALREADY_OPEN,
            view=state.active_view,
            generation=state.generation,
            committed_query=state.archive.committed_query,
        )
    state.parked_inbox = _capture_parked_inbox(owner)
    state.active_view = AGENTS_VIEW_ARCHIVE
    invalidate_agents_detail_ownership(owner)
    from ._archive_controller import request_archive_view_load

    request_archive_view_load(owner)
    return ArchiveViewOutcome(
        status=ARCHIVE_STATUS_OPENED,
        view=state.active_view,
        generation=state.generation,
        committed_query=state.archive.committed_query,
    )


def open_agents_archive_view_with_query(
    owner: Any,
    *,
    query: str,
    agent_name: str | None = None,
) -> ArchiveViewOutcome:
    """Open the Archive with an explicitly supplied scoped query.

    An explicit arrival is not the pure toggle: it replaces the Archive's
    committed query and records the exact agent name for the later routing
    phases to resolve. Returns a typed outcome so parent routing phases can
    own their toasts and trail hops.
    """
    if not agents_archive_view_enabled():
        state = _view_state(owner)
        return ArchiveViewOutcome(
            status=ARCHIVE_STATUS_DISABLED,
            view=state.active_view,
            generation=state.generation,
        )
    state = _view_state(owner)
    if state.active_view != AGENTS_VIEW_ARCHIVE:
        state.parked_inbox = _capture_parked_inbox(owner)
        state.active_view = AGENTS_VIEW_ARCHIVE
    state.archive = replace(
        state.archive,
        committed_query=query,
        selected_key=None,
        pending_exact_name=agent_name,
        loaded_pages={},
    )
    invalidate_agents_detail_ownership(owner)
    from ._archive_controller import request_archive_view_load

    request_archive_view_load(owner)
    return ArchiveViewOutcome(
        status=ARCHIVE_STATUS_OPENED,
        view=state.active_view,
        generation=state.generation,
        committed_query=query,
        exact_agent_name=agent_name,
    )


def close_agents_archive_view(owner: Any) -> ArchiveViewOutcome:
    """Return to the parked Inbox, restoring its query and selection."""
    state = _view_state(owner)
    if state.active_view != AGENTS_VIEW_ARCHIVE:
        return ArchiveViewOutcome(
            status=ARCHIVE_STATUS_ALREADY_INBOX,
            view=state.active_view,
            generation=state.generation,
        )
    parked = state.parked_inbox
    if parked is not None:
        if hasattr(owner, "_agent_search_query"):
            owner._agent_search_query = parked.committed_query
        if hasattr(owner, "current_idx"):
            owner.current_idx = parked.scroll
    state.parked_inbox = None
    state.active_view = AGENTS_VIEW_INBOX
    invalidate_agents_detail_ownership(owner)
    return ArchiveViewOutcome(
        status=ARCHIVE_STATUS_RETURNED,
        view=state.active_view,
        generation=state.generation,
    )


def get_agents_tab_selection(owner: Any) -> AgentsTabSelection:
    """Return the typed view-aware selection for read callers.

    Live-only callers keep using ``_get_selected_agent`` and never see an
    archived row. The archived agent hydrates in the archive-reader phase;
    until then an Archive selection carries its stable key, not a bundle.
    """
    state = _view_state(owner)
    if state.active_view == AGENTS_VIEW_ARCHIVE:
        if not agents_archive_view_enabled():
            return AgentsTabSelection(view=AGENTS_VIEW_INBOX, row_kind=ARCHIVE_ROW_NONE)
        key = state.archive.selected_key
        if key is None:
            return AgentsTabSelection(
                view=AGENTS_VIEW_ARCHIVE,
                row_kind=ARCHIVE_ROW_NONE,
                read_only=True,
            )
        return AgentsTabSelection(
            view=AGENTS_VIEW_ARCHIVE,
            row_kind=ARCHIVE_ROW_AGENT,
            read_only=True,
            archive_key=key,
            provenance="archive",
        )
    selector = getattr(owner, "_get_selected_agent", None)
    agent = selector() if callable(selector) else None
    if agent is None:
        return AgentsTabSelection(view=AGENTS_VIEW_INBOX, row_kind=ARCHIVE_ROW_NONE)
    return AgentsTabSelection(
        view=AGENTS_VIEW_INBOX, row_kind=ARCHIVE_ROW_AGENT, agent=agent
    )


def archive_read_only_context(owner: Any) -> ReadOnlyArchiveContext | None:
    """Return the read-only detail context for the Archive selection."""
    state = _view_state(owner)
    if not archive_detail_owns_panel(owner):
        return None
    key = state.archive.selected_key
    if key is None:
        return None
    return ReadOnlyArchiveContext(
        archive_key=key,
        detail_generation=state.generation,
        provenance="archive",
    )


__all__ = [
    "archive_detail_owns_panel",
    "archive_read_only_context",
    "agents_inbox_detail_allowed",
    "agents_view_is_archive",
    "cancel_inbox_detail_debounce",
    "capture_agents_detail_owner",
    "close_agents_archive_view",
    "get_agents_tab_selection",
    "init_agents_archive_view_state",
    "invalidate_agents_detail_ownership",
    "open_agents_archive_view",
    "open_agents_archive_view_with_query",
    "remember_agents_detail_owner",
    "scheduled_agents_detail_is_current",
]

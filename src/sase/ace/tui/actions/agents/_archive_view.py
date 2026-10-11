"""Agents-tab Archive view lifecycle, selection, and detail-ownership guards.

View-foundation seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
``owner`` is the app, duck-typed so fakes can drive every helper without a
composed widget tree. ``_get_selected_agent`` keeps its Inbox-only semantics;
read callers opt into :func:`get_agents_tab_selection` instead.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from ...models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_CONTAINER,
    ARCHIVE_ROW_NONE,
    ARCHIVE_SECTION_PULSE,
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
    is_archive_container_key,
    is_archive_row_key,
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


def init_agents_archive_view_state(owner: Any) -> AgentsArchiveViewState:
    """Initialize lifecycle state. Startup is always Inbox."""
    state = startup_agents_archive_view_state()
    try:
        from ...grouping_strategy import load_agent_archive_grouping

        state.archive.grouping = load_agent_archive_grouping()
    except Exception:
        log.debug("could not load Archive grouping preference", exc_info=True)
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
    from ._archive_reader import clear_archive_reader_runtime

    clear_archive_reader_runtime(owner)
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
    scroll_y = 0.0
    focused_panel = None
    try:
        from ...widgets import AgentList

        list_widget = owner.query_one("#agent-list-panel", AgentList)
        scroll_y = float(getattr(list_widget, "scroll_y", 0.0) or 0.0)
    except Exception:
        pass
    try:
        focused = getattr(owner, "_resolve_focused_panel", lambda: None)()
        focused_panel = str(getattr(focused, "key", None) or "") or None
    except Exception:
        pass
    folds: tuple[Any, ...] = ()
    try:
        snapshot = getattr(
            getattr(owner, "_group_fold_registry", None), "snapshot", None
        )
        if callable(snapshot):
            folds = tuple(snapshot())
    except Exception:
        pass
    deck_state = None
    try:
        capture = getattr(owner, "_capture_agents_deck_state", None)
        deck_state = capture() if callable(capture) else None
    except Exception:
        pass
    return ParkedInboxState(
        committed_query=str(getattr(owner, "_agent_search_query", "") or ""),
        selected_identity=getattr(agent, "identity", None),
        scroll=int(getattr(owner, "current_idx", 0) or 0),
        scroll_y=scroll_y,
        agent_tab=getattr(owner, "_active_agent_tab", None),
        panel_focus=getattr(getattr(owner, "focused", None), "id", None),
        panel_layout=getattr(owner, "_agent_panels_grouped", None),
        focused_panel=focused_panel,
        group_focus=getattr(owner, "_current_group_key", None),
        deck_state=deck_state,
        folds=folds,
    )


def _restore_parked_inbox(owner: Any, parked: ParkedInboxState) -> None:
    """Restore the Inbox cursor, tab, scroll, panel and fold state."""
    if hasattr(owner, "_agent_search_query"):
        owner._agent_search_query = parked.committed_query
    agents = list(getattr(owner, "_agents", ()) or [])
    if parked.selected_identity is not None:
        for index, agent in enumerate(agents):
            if getattr(agent, "identity", None) == parked.selected_identity:
                owner.current_idx = index
                break
        else:
            owner.current_idx = max(0, min(parked.scroll, max(0, len(agents) - 1)))
    elif hasattr(owner, "current_idx"):
        owner.current_idx = parked.scroll
    if parked.agent_tab is not None:
        owner._active_agent_tab = parked.agent_tab
    if parked.group_focus is not None or hasattr(owner, "_current_group_key"):
        owner._current_group_key = parked.group_focus
    registry = getattr(owner, "_group_fold_registry", None)
    restore_folds = getattr(registry, "restore", None)
    if callable(restore_folds):
        try:
            restore_folds(parked.folds)
        except Exception:
            log.debug("could not restore parked Inbox folds", exc_info=True)
    if parked.deck_state is not None:
        apply_deck = getattr(owner, "_apply_agents_deck_snapshot", None)
        if callable(apply_deck):
            try:
                apply_deck(parked.deck_state)
            except Exception:
                log.debug("could not restore parked Inbox deck state", exc_info=True)
    if parked.panel_focus:
        try:
            owner.query_one(f"#{parked.panel_focus}").focus()
        except Exception:
            pass
    if parked.scroll_y:
        try:
            from ...widgets import AgentList

            owner.query_one("#agent-list-panel", AgentList).scroll_y = parked.scroll_y
        except Exception:
            pass


def _sync_archive_chrome(owner: Any) -> None:
    """Show the active view's column. Never lets chrome failures reach the Inbox."""
    from ._archive_column import sync_archive_chrome

    try:
        sync_archive_chrome(owner, request=False)
    except Exception:
        log.debug("archive chrome sync failed", exc_info=True)


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
    _sync_archive_chrome(owner)
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
        reveal_row=None,
        loaded_pages={},
    )
    invalidate_agents_detail_ownership(owner)
    from ._archive_controller import request_archive_view_load

    request_archive_view_load(owner)
    _sync_archive_chrome(owner)
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
        _restore_parked_inbox(owner, parked)
    state.parked_inbox = None
    state.active_view = AGENTS_VIEW_INBOX
    invalidate_agents_detail_ownership(owner)
    _sync_archive_chrome(owner)
    return ArchiveViewOutcome(
        status=ARCHIVE_STATUS_RETURNED,
        view=state.active_view,
        generation=state.generation,
    )


def get_agents_tab_selection(owner: Any) -> AgentsTabSelection:
    """Return the typed view-aware selection for read callers.

    Live-only callers keep using ``_get_selected_agent`` and never see an
    archived row. A banner, page tail, or the focused Inbox pulse is not an
    agent: it resolves to ``row_kind`` ``"none"``. A run carries its stable
    key and core light row; a container carries ``container:<key>`` and the
    light row of its summary. A hydrated Archive agent is attached when the
    reader has finished loading that same key.
    """
    state = _view_state(owner)
    if state.active_view == AGENTS_VIEW_ARCHIVE:
        if not agents_archive_view_enabled():
            return AgentsTabSelection(view=AGENTS_VIEW_INBOX, row_kind=ARCHIVE_ROW_NONE)
        key = state.archive.selected_key
        if (
            key is None
            or state.archive.focused_section == ARCHIVE_SECTION_PULSE
            or not is_archive_row_key(key)
        ):
            return AgentsTabSelection(
                view=AGENTS_VIEW_ARCHIVE,
                row_kind=ARCHIVE_ROW_NONE,
                read_only=True,
            )
        from ._archive_column import archive_light_row
        from ._archive_reader import hydrated_archive_agent_for

        return AgentsTabSelection(
            view=AGENTS_VIEW_ARCHIVE,
            row_kind=(
                ARCHIVE_ROW_CONTAINER
                if is_archive_container_key(key)
                else ARCHIVE_ROW_AGENT
            ),
            agent=hydrated_archive_agent_for(owner, key),
            read_only=True,
            archive_key=key,
            provenance="archive",
            light_row=archive_light_row(owner, key),
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
    if (
        key is None
        or state.archive.focused_section == ARCHIVE_SECTION_PULSE
        or not is_archive_row_key(key)
    ):
        return None
    from ._archive_column import archive_light_row
    from ._archive_reader import hydrated_archive_agent_for

    runtime = getattr(owner, "_archive_reader_runtime", None)
    matching = getattr(runtime, "archive_key", None) == key
    return ReadOnlyArchiveContext(
        archive_key=key,
        detail_generation=state.generation,
        provenance="archive",
        light_row=archive_light_row(owner, key),
        hydrated_agent=hydrated_archive_agent_for(owner, key),
        unreadable=bool(getattr(runtime, "unreadable", False)) if matching else False,
        retained=tuple(getattr(runtime, "retained", ())) if matching else (),
        missing=tuple(getattr(runtime, "missing", ())) if matching else (),
    )


def route_archive_key(owner: Any, intent: str) -> bool:
    """Route an Agents-tab list key to the Archive. True when it consumed the key.

    Called at the top of the ``j k g G h l J K`` and Enter actions so an active
    Archive never falls through to Inbox navigation or to actions on the
    parked Inbox selection. The Inbox path pays one attribute read: the Archive
    column code only loads once the Archive is actually open.
    """
    if getattr(owner, "current_tab", "agents") != "agents":
        return False
    if not agents_view_is_archive(owner) or not archive_detail_owns_panel(owner):
        return False
    from ._archive_column_nav import dispatch_archive_intent

    dispatch_archive_intent(owner, intent)
    return True


class AgentArchiveColumnMixin:
    """Textual message handlers for the Archive column widgets.

    Handlers defer to the column code so the Inbox-only startup path never
    imports it.
    """

    def on_archive_list_cursor_moved(self, event: Any) -> None:
        from ._archive_column_nav import archive_cursor_from_widget

        archive_cursor_from_widget(self, event.key)

    def on_archive_list_item_activated(self, event: Any) -> None:
        from ._archive_column_nav import archive_activate_key

        archive_activate_key(self, event.key)

    def on_archive_pulse_activated(self, event: Any) -> None:
        from ._archive_column_nav import archive_activate_pulse

        archive_activate_pulse(self)

    def action_open_agents_archive(self) -> None:
        """Open Agents Archive, switching to Agents when needed."""
        from ...models.agent_archive_view import agents_archive_view_enabled

        if not agents_archive_view_enabled():
            return
        if getattr(self, "current_tab", None) != "agents":
            save_position = getattr(self, "_save_current_tab_position", None)
            if callable(save_position):
                save_position()
            switch = getattr(self, "_switch_to_tab", None)
            if callable(switch):
                switch("agents")
        open_agents_archive_view(self)

    def action_back_to_agents_inbox(self) -> None:
        """Return from Archive to the parked Inbox."""
        if agents_view_is_archive(self):
            if getattr(self, "current_tab", None) != "agents":
                save_position = getattr(self, "_save_current_tab_position", None)
                if callable(save_position):
                    save_position()
                switch = getattr(self, "_switch_to_tab", None)
                if callable(switch):
                    switch("agents")
            close_agents_archive_view(self)

    def action_toggle_agents_archive(self) -> None:
        """Open Archive from another tab, or toggle the Agents view in place."""
        from ...models.agent_archive_view import agents_archive_view_enabled

        if not agents_archive_view_enabled():
            return
        if getattr(self, "current_tab", None) != "agents":
            self.action_open_agents_archive()
        elif agents_view_is_archive(self):
            self.action_back_to_agents_inbox()
        else:
            open_agents_archive_view(self)


__all__ = [
    "AgentArchiveColumnMixin",
    "route_archive_key",
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

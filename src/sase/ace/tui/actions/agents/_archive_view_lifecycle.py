"""Agents-tab Archive view open/close lifecycle.

Lifecycle seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
``owner`` is the app, duck-typed so fakes can drive every helper without a
composed widget tree. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_view`, which re-exports this
module's public names.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from ...models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
    ARCHIVE_STATUS_ALREADY_INBOX,
    ARCHIVE_STATUS_ALREADY_OPEN,
    ARCHIVE_STATUS_OPENED,
    ARCHIVE_STATUS_RETURNED,
    ArchiveViewOutcome,
)
from ._archive_view_parking import (
    capture_archive_parking,
    capture_parked_inbox,
    restore_archive_parking,
    restore_parked_inbox,
)
from ._archive_view_state import (
    agents_archive_view_state,
    archive_detail_owns_panel,
    request_archive_grouping_preference_load,
)

log = logging.getLogger(__name__)


def _invalidate_agents_detail_ownership(owner: Any) -> int:
    """Invalidate earlier detail work. Returns the new generation.

    Lifecycle teardown primitive: every view switch funnels through here so
    workers started before the switch (debounced updates, async headers,
    hydration) drop instead of repainting a panel they no longer own. The
    recorded scheduled token is deliberately left in place: it now disagrees
    with the bumped generation, so the pending fire drops as stale.
    """
    state = agents_archive_view_state(owner)
    state.generation += 1
    from ._archive_reader import clear_archive_reader_runtime

    clear_archive_reader_runtime(owner)
    return state.generation


def _cancel_open_filter_session(owner: Any) -> None:
    """Close a FilterBar session before a view change.

    Matches dismiss: cancel the preview worker and refilter to the committed
    query so a late preview task cannot install the wrong query.
    """
    if not getattr(owner, "_agents_filter_session_open", False):
        return
    closer = getattr(owner, "_close_agents_filter_session", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            log.debug("could not close FilterBar session on view change", exc_info=True)
    refilter = getattr(owner, "_refilter_agents", None)
    if callable(refilter):
        try:
            refilter(refresh_content_index=False)
        except Exception:
            log.debug(
                "could not refilter after FilterBar cancel on view change",
                exc_info=True,
            )


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
    state = agents_archive_view_state(owner)
    request_archive_grouping_preference_load(owner)
    if state.active_view == AGENTS_VIEW_ARCHIVE:
        from ._archive_controller import request_archive_view_load

        request_archive_view_load(owner)
        return ArchiveViewOutcome(
            status=ARCHIVE_STATUS_ALREADY_OPEN,
            view=state.active_view,
            generation=state.generation,
            committed_query=state.archive.committed_query,
        )
    _cancel_open_filter_session(owner)
    state.parked_inbox = capture_parked_inbox(owner)
    state.active_view = AGENTS_VIEW_ARCHIVE
    _invalidate_agents_detail_ownership(owner)
    from ._archive_controller import request_archive_view_load

    request_archive_view_load(owner)
    restore_archive_parking(owner)
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
    state = agents_archive_view_state(owner)
    request_archive_grouping_preference_load(owner)
    if state.active_view != AGENTS_VIEW_ARCHIVE:
        _cancel_open_filter_session(owner)
        state.parked_inbox = capture_parked_inbox(owner)
        state.active_view = AGENTS_VIEW_ARCHIVE
    else:
        _cancel_open_filter_session(owner)
    state.archive = replace(
        state.archive,
        committed_query=query,
        selected_key=None,
        pending_exact_name=agent_name,
        arrival_outcome=None,
        reveal_row=None,
        loaded_pages={},
        restored_keys=frozenset(),
    )
    _invalidate_agents_detail_ownership(owner)
    from ._archive_controller import request_archive_view_load

    request_archive_view_load(owner)
    restore_archive_parking(owner)
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
    state = agents_archive_view_state(owner)
    if state.active_view != AGENTS_VIEW_ARCHIVE:
        return ArchiveViewOutcome(
            status=ARCHIVE_STATUS_ALREADY_INBOX,
            view=state.active_view,
            generation=state.generation,
        )
    _cancel_open_filter_session(owner)
    capture_archive_parking(owner)
    parked = state.parked_inbox
    if parked is not None:
        restore_parked_inbox(owner, parked)
    state.parked_inbox = None
    state.active_view = AGENTS_VIEW_INBOX
    state.archive.restored_keys = frozenset()
    _invalidate_agents_detail_ownership(owner)
    _sync_archive_chrome(owner)
    return ArchiveViewOutcome(
        status=ARCHIVE_STATUS_RETURNED,
        view=state.active_view,
        generation=state.generation,
    )


def mark_archive_row_restored(owner: Any, key: str) -> None:
    """Presentation overlay for sase-1jm.5 restore. Never touches corpus or counts."""
    if not key:
        return
    archive = agents_archive_view_state(owner).archive
    archive.restored_keys = archive.restored_keys | {key}
    if archive_detail_owns_panel(owner):
        from ._archive_column import refresh_column

        refresh_column(owner, request=False)


__all__ = [
    "close_agents_archive_view",
    "mark_archive_row_restored",
    "open_agents_archive_view",
    "open_agents_archive_view_with_query",
]

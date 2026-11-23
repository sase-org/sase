"""Apply still-current Archive corpus results on the UI thread.

Apply seam for the Archive controller split. Generation-safe publication,
selection preservation, and typed arrivals live here. ``apply_archive_result``
is a public name so the schedule module can call it without importing a
``_``-prefixed name. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_controller`, which does not
re-export this helper.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from ...models.agent_archive_controller import (
    ARCHIVE_CORPUS_UNREADABLE,
    ARCHIVE_CORPUS_WARM,
    ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
    ARCHIVE_REQUEST_IDLE,
    ARCHIVE_REQUEST_PREWARM,
    ARCHIVE_REQUEST_VIEW,
    ArchiveRequestSnapshot,
    ArchiveRevalidationTokens,
    preserve_archive_selected_key,
)
from ...models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    ARCHIVE_ARRIVAL_FOUND,
    ARCHIVE_ARRIVAL_MISSING,
    ARCHIVE_ARRIVAL_OWNER,
    ArchiveArrivalOutcome,
    is_archive_row_key,
)
from ...util.trace import trace_event
from ._archive_controller_build import row_identity
from ._archive_controller_support import active_view, controller, view_state

log = logging.getLogger(__name__)

__all__ = [
    "apply_archive_result",
]


def apply_archive_result(
    owner: Any,
    snapshot: ArchiveRequestSnapshot,
    result: Mapping[str, Any],
) -> None:
    state = controller(owner)
    if snapshot.generation != state.generation:
        trace_event(
            "agents.archive_apply",
            request_kind=snapshot.kind,
            outcome="stale_generation",
            changed_apply_count=0,
            unchanged_apply_count=0,
        )
        return
    state.refreshing = False
    if snapshot.kind == ARCHIVE_REQUEST_IDLE:
        state.idle_in_flight = False
    tokens = result.get("tokens")
    if isinstance(tokens, ArchiveRevalidationTokens):
        state.tokens = tokens
    display_snapshot = result.get("display_snapshot")
    display_changed = (
        display_snapshot is not None and display_snapshot != state.display_snapshot
    )
    if display_snapshot is not None:
        state.display_snapshot = display_snapshot
    link_snapshot = result.get("link_snapshot")
    if link_snapshot is not None:
        state.link_snapshot = link_snapshot
    catalog_link_identity = result.get("catalog_link_identity")
    if isinstance(catalog_link_identity, str):
        state.catalog_link_identity = catalog_link_identity
    kind = result.get("kind")
    trace_event(
        "agents.archive_apply",
        request_kind=snapshot.kind,
        outcome=(
            "read_unchanged"
            if kind == "unchanged"
            else "applied_changed"
            if kind == "built"
            else "error"
        ),
        changed_apply_count=int(kind == "built"),
        unchanged_apply_count=int(kind == "unchanged"),
        unchanged_reason=str(result.get("unchanged_reason") or ""),
    )
    if kind == "unchanged":
        # Unchanged idle results never ran a lookup; publishing from them
        # would report a false missing arrival for a queued exact-name open.
        if display_changed:
            _notify_snapshot_applied(owner)
        _maybe_coalesce_idle(owner, snapshot)
        return
    if kind in {"unreadable", "error"}:
        state.corpus = None
        state.status = ARCHIVE_CORPUS_UNREADABLE
        state.error_message = ARCHIVE_INDEX_UNAVAILABLE_MESSAGE
        state.summary = None
        state.windows = ()
        state.identities = ()
        state.count = 0
        from ._archive_shelf import request_archive_shelf_refresh

        request_archive_shelf_refresh(owner)
        _publish_arrival(owner, snapshot, result)
        _notify_snapshot_applied(owner)
        _maybe_coalesce_idle(owner, snapshot)
        return
    facets = result.get("facets")
    if isinstance(facets, Mapping):
        state.link_facets = facets
    state.corpus = result.get("corpus")
    state.profile = result.get("profile")
    state.status = str(result.get("status") or ARCHIVE_CORPUS_WARM)
    state.error_message = (
        str(result["error_message"])
        if result.get("error_message") is not None
        else None
    )
    state.indexed_rows = int(result.get("indexed_rows") or 0)
    state.summary = (
        result.get("summary") if isinstance(result.get("summary"), Mapping) else None
    )
    windows = result.get("windows")
    state.windows = windows if isinstance(windows, tuple) else ()
    identities = result.get("identities")
    state.identities = identities if isinstance(identities, tuple) else ()
    state.count = int(result.get("count") or 0)
    state.applied_query = snapshot.query
    state.applied_grouping = snapshot.grouping
    state.applied_expanded = tuple(snapshot.expanded_containers)
    if state.corpus is not None:
        state.prewarm_started = True
        state.prewarm_pending = False
    from ._archive_shelf import request_archive_shelf_refresh

    request_archive_shelf_refresh(owner)
    _apply_selection(owner, snapshot, result)
    _notify_snapshot_applied(owner)
    _maybe_coalesce_idle(owner, snapshot)


def _maybe_coalesce_idle(owner: Any, snapshot: ArchiveRequestSnapshot) -> None:
    state = controller(owner)
    if snapshot.kind != ARCHIVE_REQUEST_IDLE:
        return
    if snapshot.generation != state.generation:
        return
    from ._archive_controller_schedule import schedule_request

    if state.explicit_open_queued:
        state.idle_coalesced = False
        state.explicit_open_queued = False
        schedule_request(owner, kind=ARCHIVE_REQUEST_VIEW)
        return
    if not state.idle_coalesced:
        return
    state.idle_coalesced = False
    schedule_request(owner, kind=ARCHIVE_REQUEST_IDLE)


def _notify_snapshot_applied(owner: Any) -> None:
    """Let the Archive column repaint from the freshly published snapshot."""
    from ._archive_column import on_archive_snapshot_applied

    try:
        on_archive_snapshot_applied(owner)
    except Exception:
        log.debug("archive column snapshot hook failed", exc_info=True)


def _apply_selection(
    owner: Any,
    snapshot: ArchiveRequestSnapshot,
    result: Mapping[str, Any],
) -> None:
    if active_view(owner) != AGENTS_VIEW_ARCHIVE:
        _publish_arrival(owner, snapshot, result)
        return
    view = view_state(owner)
    archive = getattr(view, "archive", None)
    if archive is None:
        _publish_arrival(owner, snapshot, result)
        return
    identities = result.get("identities")
    new_identities = identities if isinstance(identities, tuple) else ()
    current_key = getattr(archive, "selected_key", None)
    lookup_row = result.get("lookup_row")
    if isinstance(lookup_row, Mapping):
        looked_up = row_identity(lookup_row)
        if looked_up is not None:
            archive.selected_key = looked_up
            archive.reveal_row = dict(lookup_row)
            _publish_arrival(owner, snapshot, result)
            return
    if snapshot.pending_exact_name:
        _publish_arrival(owner, snapshot, result)
        return
    if current_key is not None and not is_archive_row_key(str(current_key)):
        return  # a banner or page tail cursor is not an identity to preserve
    if snapshot.kind == ARCHIVE_REQUEST_PREWARM and current_key is None:
        return
    preserved = preserve_archive_selected_key(
        snapshot.previous_identities,
        str(current_key) if current_key else snapshot.selected_key,
        new_identities,
    )
    if new_identities or current_key is None:
        archive.selected_key = preserved


def _row_agent_name(row: Mapping[str, Any] | None) -> str | None:
    if not isinstance(row, Mapping):
        return None
    for key in ("name", "agent_name", "cl_name"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _publish_arrival(
    owner: Any,
    snapshot: ArchiveRequestSnapshot,
    result: Mapping[str, Any],
) -> None:
    requested = snapshot.pending_exact_name
    if not requested:
        return
    view = view_state(owner)
    archive = getattr(view, "archive", None)
    if archive is None:
        return
    lookup_row = result.get("lookup_row")
    row = lookup_row if isinstance(lookup_row, Mapping) else None
    row_name = _row_agent_name(row)
    if row is None:
        status = ARCHIVE_ARRIVAL_MISSING
        selected_key = None
    elif row_name == requested:
        status = ARCHIVE_ARRIVAL_FOUND
        selected_key = row_identity(row)
    else:
        status = ARCHIVE_ARRIVAL_OWNER
        selected_key = row_identity(row)
    outcome = ArchiveArrivalOutcome(
        status=status,
        requested_name=requested,
        selected_key=selected_key,
        row_name=row_name,
    )
    archive.pending_exact_name = None
    archive.arrival_outcome = outcome
    callback = getattr(owner, "_archive_arrival_callback", None)
    if callable(callback):
        try:
            callback(outcome)
        except Exception:
            log.debug("archive arrival callback failed", exc_info=True)

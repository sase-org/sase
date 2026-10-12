"""Pump-free Archive corpus controller around the shared core cache.

Corpus-controller seam for the Agents Archive epic (child epic
``sase-1jm.3.1``). UI callbacks only schedule work or apply still-current
results. Disk probing, facet loading, compile, and corpus queries run
off-thread via :func:`spawn_pump_free_task`. With the beta off this module
probes nothing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from ...models.agent_archive_controller import (
    ARCHIVE_CORPUS_COLD,
    ARCHIVE_CORPUS_LOADING,
    ARCHIVE_CORPUS_MISSING,
    ARCHIVE_CORPUS_UNREADABLE,
    ARCHIVE_CORPUS_WARM,
    ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
    ARCHIVE_REQUEST_IDLE,
    ARCHIVE_REQUEST_PREWARM,
    ARCHIVE_REQUEST_QUERY,
    ARCHIVE_REQUEST_VIEW,
    AgentsArchiveControllerState,
    ArchiveCorpusSnapshot,
    ArchiveInboxPulse,
    ArchivePageWindow,
    ArchiveRequestSnapshot,
    ArchiveRevalidationTokens,
    preserve_archive_selected_key,
    startup_agents_archive_controller_state,
)
from ._archive_controller_build import build_archive_result, row_identity
from ...models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
    ARCHIVE_ARRIVAL_FOUND,
    ARCHIVE_ARRIVAL_MISSING,
    ARCHIVE_ARRIVAL_OWNER,
    ARCHIVE_DEFAULT_GROUPING,
    ARCHIVE_DEFAULT_QUERY,
    ArchiveArrivalOutcome,
    agents_archive_view_enabled,
    is_archive_row_key,
)
from ...util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)

_ARCHIVE_TASK_REGISTRY = "_archive_controller_tasks"
_ARCHIVE_TASK_NAME = "sase-archive-corpus"


def _controller(owner: Any) -> AgentsArchiveControllerState:
    state = getattr(owner, "_agents_archive_controller", None)
    if isinstance(state, AgentsArchiveControllerState):
        return state
    state = startup_agents_archive_controller_state()
    owner._agents_archive_controller = state
    return state


def init_agents_archive_controller(owner: Any) -> AgentsArchiveControllerState:
    """Install a cold controller. Startup never probes the archive."""
    state = startup_agents_archive_controller_state()
    owner._agents_archive_controller = state
    return state


def archive_corpus_snapshot(owner: Any) -> ArchiveCorpusSnapshot:
    """Return the published generation-safe corpus snapshot."""
    state = _controller(owner)
    return ArchiveCorpusSnapshot(
        status=state.status,
        generation=state.generation,
        error_message=state.error_message,
        indexed_rows=state.indexed_rows,
        refreshing=state.refreshing,
        summary=state.summary,
        windows=state.windows,
        identities=state.identities,
        count=state.count,
        query=state.last_query,
        grouping=state.last_grouping,
        tokens=state.tokens,
        warm=state.corpus is not None,
        applied_query=state.applied_query,
        applied_grouping=state.applied_grouping,
        applied_expanded=state.applied_expanded,
        timezone=str(getattr(state.corpus, "timezone", "") or ""),
        display_snapshot=state.display_snapshot,
    )


def archive_inbox_pulse(owner: Any) -> ArchiveInboxPulse:
    """Return the last Inbox pulse captured from an applied Inbox roster."""
    return _controller(owner).pulse


def archive_corpus_is_warm(owner: Any) -> bool:
    """Return whether a warm corpus handle is held."""
    return _controller(owner).corpus is not None


def _view_state(owner: Any) -> Any:
    return getattr(owner, "_agents_archive_view", None)


def _active_view(owner: Any) -> str:
    view = _view_state(owner)
    active = getattr(view, "active_view", None)
    return str(active) if active else AGENTS_VIEW_INBOX


def _ui_is_idle(owner: Any) -> bool:
    nav = getattr(owner, "_nav_gate", None)
    is_navigating = getattr(nav, "is_navigating", None)
    if callable(is_navigating) and is_navigating():
        return False
    prompt = getattr(owner, "_prompt_input_active", None)
    if callable(prompt) and prompt():
        return False
    return True


def refresh_archive_inbox_pulse(owner: Any) -> ArchiveInboxPulse:
    """Snapshot Inbox counts from already-applied roster state.

    Prefers the Inbox header's cached metrics (so the pulse can never disagree
    with it and costs nothing extra); a bare roster scan is the fallback.
    """
    pulse = ArchiveInboxPulse()
    if not agents_archive_view_enabled():
        _controller(owner).pulse = pulse
        return pulse
    pulse = _pulse_from_header_metrics(owner) or _pulse_from_roster(owner)
    _controller(owner).pulse = pulse
    from ._archive_column import update_archive_pulse

    update_archive_pulse(owner)
    return pulse


def _pulse_from_header_metrics(owner: Any) -> ArchiveInboxPulse | None:
    metrics = getattr(owner, "_agent_info_metrics", None)
    if not callable(metrics):
        return None
    try:
        unread, asking, running, waiting, _failed, _read, total, *_rest = metrics()
    except Exception:
        return None
    return ArchiveInboxPulse(
        total=int(total),
        running=int(running),
        waiting=int(waiting),
        unread=int(unread),
        attention=int(asking),
    )


def _pulse_from_roster(owner: Any) -> ArchiveInboxPulse:
    agents = getattr(owner, "_agents", None) or ()
    running = 0
    waiting = 0
    for agent in agents:
        status = str(getattr(agent, "status", "") or "")
        if status == "RUNNING":
            running += 1
        elif status == "WAITING":
            waiting += 1
    unread = len(getattr(owner, "_unread_completed_agent_ids", ()) or ())
    attention = int(getattr(owner, "_pending_attention_count", 0) or 0)
    return ArchiveInboxPulse(
        total=len(tuple(agents)),
        running=running,
        waiting=waiting,
        unread=unread,
        attention=attention,
    )


def note_inbox_applied_for_archive(owner: Any, load_state: Any = None) -> None:
    """Inbox-applied hook: capture pulse and arm the one-shot prewarm gate.

    The gate opens only after a complete Inbox load, never after compose,
    a bounded first paint, or an incomplete reconciliation. Failures here
    never disturb Inbox state.
    """
    try:
        if not agents_archive_view_enabled():
            return
        refresh_archive_inbox_pulse(owner)
        from ._archive_shelf import request_archive_shelf_refresh

        request_archive_shelf_refresh(owner)
        state = _controller(owner)
        state.inbox_load_scheduled = False
        if not _load_is_complete_inbox(load_state):
            return
        state.inbox_complete_applied = True
        if state.explicit_open_queued:
            state.explicit_open_queued = False
            _schedule_request(owner, kind=ARCHIVE_REQUEST_VIEW)
            return
        _maybe_arm_prewarm(owner)
    except Exception:
        log.debug("archive inbox-applied hook failed", exc_info=True)


def _load_is_complete_inbox(load_state: Any) -> bool:
    if load_state is None:
        return False
    from ._loading_apply_history import roster_complete_for_load

    return roster_complete_for_load(load_state)


def _maybe_arm_prewarm(owner: Any) -> None:
    state = _controller(owner)
    if not state.inbox_complete_applied or state.prewarm_started:
        return
    if state.corpus is not None:
        state.prewarm_started = True
        state.prewarm_pending = False
        return
    if not _ui_is_idle(owner):
        state.prewarm_pending = True
        return
    state.prewarm_pending = False
    state.prewarm_started = True
    _schedule_request(owner, kind=ARCHIVE_REQUEST_PREWARM)


def schedule_archive_idle_tick(owner: Any) -> None:
    """Quiet-tick hook. Compares cheap signatures only; never scans catalogs."""
    try:
        if not agents_archive_view_enabled():
            return
        if not _ui_is_idle(owner):
            return
        state = _controller(owner)
        if not state.inbox_complete_applied:
            return
        if state.explicit_open_queued:
            state.explicit_open_queued = False
            _schedule_request(owner, kind=ARCHIVE_REQUEST_VIEW)
            return
        if state.refreshing:
            return
        if state.idle_in_flight:
            state.idle_coalesced = True
            return
        if state.prewarm_pending and not state.prewarm_started:
            _maybe_arm_prewarm(owner)
            return
        if not state.prewarm_started and state.corpus is None:
            _maybe_arm_prewarm(owner)
            return
        _schedule_request(owner, kind=ARCHIVE_REQUEST_IDLE)
    except Exception:
        log.debug("archive idle tick failed", exc_info=True)


def request_archive_view_load(owner: Any) -> None:
    """Queue or start corpus work for an explicit Archive open (``,a``)."""
    if not agents_archive_view_enabled():
        return
    state = _controller(owner)
    if state.status in {ARCHIVE_CORPUS_COLD, ARCHIVE_CORPUS_MISSING} or (
        state.corpus is None and state.status != ARCHIVE_CORPUS_LOADING
    ):
        state.status = ARCHIVE_CORPUS_LOADING
        state.error_message = None
    _preplan_view_windows(owner)
    if not state.inbox_complete_applied:
        state.explicit_open_queued = True
        _schedule_inbox_load_for_gate(owner)
        return
    if not _ui_is_idle(owner):
        state.explicit_open_queued = True
        return
    _schedule_request(owner, kind=ARCHIVE_REQUEST_VIEW)


def _preplan_view_windows(owner: Any) -> None:
    """Carry the held summary's windows into the open's own request.

    A warm reopen then needs one corpus round trip instead of a summary
    request followed by a window request.
    """
    from ._archive_column import plan_archive_view_windows

    try:
        windows = plan_archive_view_windows(owner)
    except Exception:
        log.debug("archive window preplan failed", exc_info=True)
        return
    if windows is not None:
        state = _controller(owner)
        state.last_windows = windows
        archive = getattr(_view_state(owner), "archive", None)
        state.last_expanded = tuple(getattr(archive, "expanded_containers", ()) or ())


def request_archive_windows(
    owner: Any,
    windows: Sequence[ArchivePageWindow],
    *,
    expanded_containers: Sequence[str] | None = None,
) -> int:
    """Request page windows against the warm handle. Returns the generation."""
    if not agents_archive_view_enabled():
        return _controller(owner).generation
    state = _controller(owner)
    state.last_windows = tuple(windows)
    if expanded_containers is not None:
        state.last_expanded = tuple(expanded_containers)
    if not state.inbox_complete_applied:
        state.explicit_open_queued = True
        _schedule_inbox_load_for_gate(owner)
        return state.generation
    return _schedule_request(owner, kind=ARCHIVE_REQUEST_QUERY)


def note_inbox_load_finished_for_archive(owner: Any) -> None:
    """Reset the Inbox-load gate so a later Archive open can retry after a miss."""
    _controller(owner).inbox_load_scheduled = False


def cancel_archive_controller(owner: Any) -> None:
    """Cancel in-flight Archive tasks at teardown."""
    for attr in (_ARCHIVE_TASK_REGISTRY, "_archive_shelf_tasks"):
        for task in tuple(getattr(owner, attr, ())):
            cancel = getattr(task, "cancel", None)
            if callable(cancel):
                cancel()


def _schedule_inbox_load_for_gate(owner: Any) -> None:
    state = _controller(owner)
    if state.inbox_load_scheduled:
        return
    schedule = getattr(owner, "_schedule_agents_async_refresh", None)
    if not callable(schedule):
        return
    state.inbox_load_scheduled = True
    try:
        schedule(source="archive_prewarm_gate")
    except TypeError:
        try:
            schedule()
        except Exception:
            state.inbox_load_scheduled = False
            raise
    except Exception:
        state.inbox_load_scheduled = False
        raise


def _schedule_request(owner: Any, *, kind: str) -> int:
    state = _controller(owner)
    view = _view_state(owner)
    archive = getattr(view, "archive", None)
    query = str(getattr(archive, "committed_query", None) or ARCHIVE_DEFAULT_QUERY)
    grouping = str(getattr(archive, "grouping", None) or ARCHIVE_DEFAULT_GROUPING)
    selected_key = getattr(archive, "selected_key", None)
    expanded = tuple(getattr(archive, "expanded_containers", ()) or ())
    if state.last_expanded:
        expanded = state.last_expanded
    windows = state.last_windows
    pending_exact_name = getattr(archive, "pending_exact_name", None)
    state.generation += 1
    snapshot = ArchiveRequestSnapshot(
        generation=state.generation,
        kind=kind,
        query=query,
        grouping=grouping,
        windows=windows,
        expanded_containers=expanded,
        selected_key=str(selected_key) if selected_key else None,
        view=_active_view(owner),
        previous_identities=state.identities,
        link_facets=state.link_facets,
        tokens=state.tokens,
        corpus=state.corpus,
        profile=state.profile,
        pending_exact_name=str(pending_exact_name) if pending_exact_name else None,
    )
    state.last_query = query
    state.last_grouping = grouping
    if kind == ARCHIVE_REQUEST_IDLE:
        state.idle_in_flight = True
    else:
        state.idle_in_flight = False
        state.idle_coalesced = False
    if kind != ARCHIVE_REQUEST_IDLE or state.corpus is None:
        state.refreshing = True
        if state.corpus is None and state.status == ARCHIVE_CORPUS_COLD:
            state.status = ARCHIVE_CORPUS_LOADING
    _spawn_archive_task(owner, _run_archive_request(owner, snapshot))
    return snapshot.generation


def _spawn_archive_task(owner: Any, coro: Any) -> Any:
    spawner = getattr(owner, "_archive_spawn", None)
    if callable(spawner):
        task = spawner(
            owner,
            coro,
            name=_ARCHIVE_TASK_NAME,
            registry_attr=_ARCHIVE_TASK_REGISTRY,
        )
    else:
        task = spawn_pump_free_task(
            owner,
            coro,
            name=_ARCHIVE_TASK_NAME,
            registry_attr=_ARCHIVE_TASK_REGISTRY,
        )
    if task is None:
        return None
    registry = getattr(owner, _ARCHIVE_TASK_REGISTRY, None)
    if registry is None:
        registry = set()
        setattr(owner, _ARCHIVE_TASK_REGISTRY, registry)
    try:
        registry.add(task)
    except TypeError:
        pass
    return task


async def _run_archive_request(owner: Any, snapshot: ArchiveRequestSnapshot) -> None:
    result: Mapping[str, Any]
    try:
        runner = getattr(owner, "_archive_run_off_thread", None)
        if callable(runner):
            built = await runner(lambda: build_archive_result(owner, snapshot))
        else:
            built = await asyncio.to_thread(build_archive_result, owner, snapshot)
        result = built if isinstance(built, Mapping) else {"kind": "error"}
    except Exception:
        log.debug("archive request worker failed", exc_info=True)
        result = {"kind": "error"}
    _apply_archive_result(owner, snapshot, result)


def _apply_archive_result(
    owner: Any,
    snapshot: ArchiveRequestSnapshot,
    result: Mapping[str, Any],
) -> None:
    state = _controller(owner)
    if snapshot.generation != state.generation:
        return
    state.refreshing = False
    if snapshot.kind == ARCHIVE_REQUEST_IDLE:
        state.idle_in_flight = False
    tokens = result.get("tokens")
    if isinstance(tokens, ArchiveRevalidationTokens):
        state.tokens = tokens
    display_snapshot = result.get("display_snapshot")
    if display_snapshot is not None:
        state.display_snapshot = display_snapshot
    kind = result.get("kind")
    if kind == "unchanged":
        # Unchanged idle results never ran a lookup; publishing from them
        # would report a false missing arrival for a queued exact-name open.
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
    state = _controller(owner)
    if snapshot.kind != ARCHIVE_REQUEST_IDLE:
        return
    if snapshot.generation != state.generation:
        return
    if state.explicit_open_queued:
        state.idle_coalesced = False
        state.explicit_open_queued = False
        _schedule_request(owner, kind=ARCHIVE_REQUEST_VIEW)
        return
    if not state.idle_coalesced:
        return
    state.idle_coalesced = False
    _schedule_request(owner, kind=ARCHIVE_REQUEST_IDLE)


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
    if _active_view(owner) != AGENTS_VIEW_ARCHIVE:
        _publish_arrival(owner, snapshot, result)
        return
    view = _view_state(owner)
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
    view = _view_state(owner)
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


__all__ = [
    "archive_corpus_is_warm",
    "archive_corpus_snapshot",
    "archive_inbox_pulse",
    "cancel_archive_controller",
    "init_agents_archive_controller",
    "note_inbox_applied_for_archive",
    "note_inbox_load_finished_for_archive",
    "refresh_archive_inbox_pulse",
    "request_archive_view_load",
    "request_archive_windows",
    "schedule_archive_idle_tick",
]

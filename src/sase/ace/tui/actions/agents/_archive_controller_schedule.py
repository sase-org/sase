"""Schedule Archive corpus work off the UI thread.

Schedule seam for the Archive controller split. Explicit opens, idle ticks,
window requests, and the one-shot prewarm gate live here. ``schedule_request``
is a public name so the apply module can coalesce a follow-up without
importing a ``_``-prefixed name. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_controller`, which re-exports
the public scheduling names and does not re-export ``schedule_request``.
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
    ARCHIVE_REQUEST_IDLE,
    ARCHIVE_REQUEST_PREWARM,
    ARCHIVE_REQUEST_QUERY,
    ARCHIVE_REQUEST_VIEW,
    ArchivePageWindow,
    ArchiveRequestSnapshot,
)
from ...models.agent_archive_view import (
    ARCHIVE_DEFAULT_GROUPING,
    ARCHIVE_DEFAULT_QUERY,
)
from ...util.pump_tasks import spawn_pump_free_task
from ._archive_controller_apply import apply_archive_result
from ._archive_controller_build import build_archive_result
from ._archive_controller_pulse import refresh_archive_inbox_pulse
from ._archive_controller_support import (
    ARCHIVE_TASK_REGISTRY,
    active_view,
    controller,
    view_state,
)

log = logging.getLogger(__name__)

_ARCHIVE_TASK_NAME = "sase-archive-corpus"

__all__ = [
    "lookup_archive_light_row",
    "note_inbox_applied_for_archive",
    "request_archive_view_load",
    "request_archive_windows",
    "schedule_archive_idle_tick",
    "schedule_request",
]


def lookup_archive_light_row(owner: Any, name: str) -> Mapping[str, Any] | None:
    """Blocking exact-name lookup against the Archive corpus.

    Call off-thread only: link arrivals probe here before opening the
    Archive, so a miss toasts without touching the parked query, selection,
    or pages. Reads the warm handle when its tokens still match and compiles
    otherwise; publishes nothing, so concurrent view loads keep their own
    generations.
    """
    from ...models.agent_archive_view import (
        ARCHIVE_DEFAULT_GROUPING,
        ARCHIVE_DEFAULT_QUERY,
    )

    state = controller(owner)
    archive = getattr(view_state(owner), "archive", None)
    snapshot = ArchiveRequestSnapshot(
        generation=state.generation,
        kind=ARCHIVE_REQUEST_QUERY,
        query=ARCHIVE_DEFAULT_QUERY,
        grouping=str(getattr(archive, "grouping", None) or ARCHIVE_DEFAULT_GROUPING),
        windows=(),
        expanded_containers=tuple(getattr(archive, "expanded_containers", ()) or ()),
        selected_key=None,
        view=active_view(owner),
        previous_identities=state.identities,
        link_facets=state.link_facets,
        tokens=state.tokens,
        corpus=state.corpus,
        profile=state.profile,
        link_snapshot=state.link_snapshot,
        catalog_link_identity=state.catalog_link_identity,
        pending_exact_name=name,
    )
    result = build_archive_result(owner, snapshot)
    row = result.get("lookup_row")
    return dict(row) if isinstance(row, Mapping) else None


def _ui_is_idle(owner: Any) -> bool:
    nav = getattr(owner, "_nav_gate", None)
    is_navigating = getattr(nav, "is_navigating", None)
    if callable(is_navigating) and is_navigating():
        return False
    prompt = getattr(owner, "_prompt_input_active", None)
    if callable(prompt) and prompt():
        return False
    return True


def note_inbox_applied_for_archive(owner: Any, load_state: Any = None) -> None:
    """Inbox-applied hook: capture pulse and arm the one-shot prewarm gate.

    The gate opens only after a complete Inbox load, never after compose,
    a bounded first paint, or an incomplete reconciliation. Failures here
    never disturb Inbox state.
    """
    try:
        refresh_archive_inbox_pulse(owner)
        from ._archive_shelf import request_archive_shelf_refresh

        request_archive_shelf_refresh(owner)
        state = controller(owner)
        state.inbox_load_scheduled = False
        if not _load_is_complete_inbox(load_state):
            return
        state.inbox_complete_applied = True
        if state.explicit_open_queued:
            state.explicit_open_queued = False
            schedule_request(owner, kind=ARCHIVE_REQUEST_VIEW)
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
    state = controller(owner)
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
    schedule_request(owner, kind=ARCHIVE_REQUEST_PREWARM)


def schedule_archive_idle_tick(owner: Any) -> None:
    """Quiet-tick hook. Compares cheap signatures only; never scans catalogs."""
    try:
        if not _ui_is_idle(owner):
            return
        state = controller(owner)
        if not state.inbox_complete_applied:
            return
        if state.explicit_open_queued:
            state.explicit_open_queued = False
            schedule_request(owner, kind=ARCHIVE_REQUEST_VIEW)
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
        schedule_request(owner, kind=ARCHIVE_REQUEST_IDLE)
    except Exception:
        log.debug("archive idle tick failed", exc_info=True)


def request_archive_view_load(owner: Any) -> None:
    """Queue or start corpus work for an explicit Archive open (``,a``)."""
    state = controller(owner)
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
    schedule_request(owner, kind=ARCHIVE_REQUEST_VIEW)


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
        state = controller(owner)
        state.last_windows = windows
        archive = getattr(view_state(owner), "archive", None)
        state.last_expanded = tuple(getattr(archive, "expanded_containers", ()) or ())


def request_archive_windows(
    owner: Any,
    windows: Sequence[ArchivePageWindow],
    *,
    expanded_containers: Sequence[str] | None = None,
) -> int:
    """Request page windows against the warm handle. Returns the generation."""
    state = controller(owner)
    state.last_windows = tuple(windows)
    if expanded_containers is not None:
        state.last_expanded = tuple(expanded_containers)
    if not state.inbox_complete_applied:
        state.explicit_open_queued = True
        _schedule_inbox_load_for_gate(owner)
        return state.generation
    return schedule_request(owner, kind=ARCHIVE_REQUEST_QUERY)


def _schedule_inbox_load_for_gate(owner: Any) -> None:
    state = controller(owner)
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


def schedule_request(owner: Any, *, kind: str) -> int:
    state = controller(owner)
    view = view_state(owner)
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
        view=active_view(owner),
        previous_identities=state.identities,
        link_facets=state.link_facets,
        tokens=state.tokens,
        corpus=state.corpus,
        profile=state.profile,
        pending_exact_name=str(pending_exact_name) if pending_exact_name else None,
        link_snapshot=state.link_snapshot,
        catalog_link_identity=state.catalog_link_identity,
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
            registry_attr=ARCHIVE_TASK_REGISTRY,
        )
    else:
        task = spawn_pump_free_task(
            owner,
            coro,
            name=_ARCHIVE_TASK_NAME,
            registry_attr=ARCHIVE_TASK_REGISTRY,
        )
    if task is None:
        return None
    registry = getattr(owner, ARCHIVE_TASK_REGISTRY, None)
    if registry is None:
        registry = set()
        setattr(owner, ARCHIVE_TASK_REGISTRY, registry)
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
    apply_archive_result(owner, snapshot, result)

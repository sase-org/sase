"""Archive-controller pulse, snapshot, and teardown.

Pulse seam for the Archive controller split. Inbox-count capture, the
generation-safe corpus snapshot, cold init, and task cancel live here.
The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_controller`, which re-exports
this module's public names.
"""

from __future__ import annotations

from typing import Any

from ...models.agent_archive_controller import (
    AgentsArchiveControllerState,
    ArchiveCorpusSnapshot,
    ArchiveInboxPulse,
    startup_agents_archive_controller_state,
)
from ._archive_controller_support import ARCHIVE_TASK_REGISTRY, controller

__all__ = [
    "archive_corpus_snapshot",
    "archive_inbox_pulse",
    "cancel_archive_controller",
    "init_agents_archive_controller",
    "note_inbox_load_finished_for_archive",
    "refresh_archive_inbox_pulse",
]


def init_agents_archive_controller(owner: Any) -> AgentsArchiveControllerState:
    """Install a cold controller. Startup never probes the archive."""
    state = startup_agents_archive_controller_state()
    owner._agents_archive_controller = state
    return state


def archive_corpus_snapshot(owner: Any) -> ArchiveCorpusSnapshot:
    """Return the published generation-safe corpus snapshot."""
    state = controller(owner)
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
    return controller(owner).pulse


def refresh_archive_inbox_pulse(owner: Any) -> ArchiveInboxPulse:
    """Snapshot Inbox counts from already-applied roster state.

    Prefers the Inbox header's cached metrics (so the pulse can never disagree
    with it and costs nothing extra); a bare roster scan is the fallback.
    """
    pulse = _pulse_from_header_metrics(owner) or _pulse_from_roster(owner)
    controller(owner).pulse = pulse
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


def note_inbox_load_finished_for_archive(owner: Any) -> None:
    """Reset the Inbox-load gate so a later Archive open can retry after a miss."""
    controller(owner).inbox_load_scheduled = False


def cancel_archive_controller(owner: Any) -> None:
    """Cancel in-flight Archive tasks at teardown."""
    for attr in (ARCHIVE_TASK_REGISTRY, "_archive_shelf_tasks"):
        for task in tuple(getattr(owner, attr, ())):
            cancel = getattr(task, "cancel", None)
            if callable(cancel):
                cancel()

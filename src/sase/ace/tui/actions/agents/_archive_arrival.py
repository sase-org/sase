"""Shared exact-name arrivals into the Agents Archive."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ...util.pump_tasks import spawn_pump_free_task

_ARRIVAL_TASK_NAME = "sase-archive-arrival"
_ARRIVAL_TASK_REGISTRY = "_archive_arrival_tasks"


def _archive_name_query(name: str) -> str:
    """Return a safely quoted exact-name predicate in the Archive scope."""
    return f"in:archive name:{json.dumps(name, ensure_ascii=False)}"


def _dismissed_when(owner: Any) -> str:
    state = getattr(owner, "_agents_archive_view", None)
    archive = getattr(state, "archive", None)
    row = getattr(archive, "reveal_row", None)
    dismissed_at = row.get("dismissed_at") if isinstance(row, Mapping) else None
    if not isinstance(dismissed_at, str) or not dismissed_at:
        return "dismissed"
    try:
        timestamp = datetime.fromisoformat(dismissed_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        days = max(0, (datetime.now(UTC).date() - timestamp.date()).days)
        date_label = f"{timestamp.strftime('%b')} {timestamp.day}"
    except (ValueError, OverflowError):
        return "dismissed"
    age = "today" if days == 0 else "yesterday" if days == 1 else f"{days} days ago"
    return f"dismissed {date_label} ({age})"


def _switch_to_agents(owner: Any) -> str:
    old_tab = str(getattr(owner, "current_tab", "agents"))
    if old_tab != "agents":
        save = getattr(owner, "_save_current_tab_position", None)
        if callable(save):
            save()
        switch = getattr(owner, "_switch_to_tab", None)
        if callable(switch):
            switch("agents")
        else:
            owner.current_tab = "agents"
    return old_tab


def open_archive_for_agent(
    owner: Any,
    name: str,
    *,
    source: str,
    origin: Any = None,
    return_on_miss: bool = False,
) -> bool:
    """Probe the Archive off-thread, then open it only on a hit.

    The exact lookup runs first through the Archive controller's pump-free
    worker. On a hit the Archive opens with ``in:archive name:"<name>"`` and
    selects the row, recording one Ctrl+O hop. On a miss it toasts
    ``agent:… has no record on this machine`` and changes nothing: no tab
    switch, no parked query replacement, no selection reset. A newer arrival
    supersedes an in-flight one, which then lands silently.
    """
    if origin is None:
        capture = getattr(owner, "_current_link_trail_origin", None)
        origin = capture() if callable(capture) else None
    sequence = int(getattr(owner, "_archive_arrival_seq", 0) or 0) + 1
    owner._archive_arrival_seq = sequence
    owner._archive_arrival_callback = None
    coro = _lookup_first_open(
        owner,
        name,
        source=source,
        origin=origin,
        return_on_miss=return_on_miss,
        sequence=sequence,
    )
    spawner = getattr(owner, "_archive_spawn", None)
    if callable(spawner):
        spawner(
            owner,
            coro,
            name=_ARRIVAL_TASK_NAME,
            registry_attr=_ARRIVAL_TASK_REGISTRY,
        )
    else:
        spawn_pump_free_task(
            owner,
            coro,
            name=_ARRIVAL_TASK_NAME,
            registry_attr=_ARRIVAL_TASK_REGISTRY,
        )
    return True


async def _lookup_first_open(
    owner: Any,
    name: str,
    *,
    source: str,
    origin: Any,
    return_on_miss: bool,
    sequence: int,
) -> None:
    """Run the exact lookup, then open the Archive only when it hits."""
    from ._archive_controller import lookup_archive_light_row

    runner = getattr(owner, "_archive_run_off_thread", None)
    if callable(runner):
        row = await runner(lambda: lookup_archive_light_row(owner, name))
    else:
        row = await asyncio.to_thread(lookup_archive_light_row, owner, name)
    if getattr(owner, "_archive_arrival_seq", sequence) != sequence:
        return
    if row is None:
        notify = getattr(owner, "notify", None)
        if callable(notify):
            notify(f"agent:{name} has no record on this machine", severity="warning")
        return
    _open_archive_after_lookup(
        owner,
        name,
        source=source,
        origin=origin,
        return_on_miss=return_on_miss,
    )


def _open_archive_after_lookup(
    owner: Any,
    name: str,
    *,
    source: str,
    origin: Any,
    return_on_miss: bool,
) -> None:
    """Open the Archive for a confirmed hit and announce the arrival.

    Exact lookup and row hydration run through the Archive controller's
    pump-free worker. The caller may supply a link-trail origin; it is added
    only after the controller confirms the row (or its workflow owner). A
    post-lookup race that resolves to missing keeps the previous
    ``return_on_miss`` contract.
    """
    from ._archive_view import (
        close_agents_archive_view,
        open_agents_archive_view_with_query,
    )

    old_tab = _switch_to_agents(owner)
    owner._archive_arrival_callback = None
    outcome = open_agents_archive_view_with_query(
        owner,
        query=_archive_name_query(name),
        agent_name=name,
    )
    generation = outcome.generation

    def arrived(result: Any) -> None:
        state = getattr(owner, "_agents_archive_view", None)
        if (
            state is None
            or state.generation != generation
            or getattr(state, "active_view", None) != "archive"
        ):
            return
        owner._archive_arrival_callback = None
        if getattr(result, "status", None) == "missing":
            if return_on_miss:
                close_agents_archive_view(owner)
                if old_tab != "agents":
                    switch = getattr(owner, "_switch_to_tab", None)
                    if callable(switch):
                        switch(old_tab)
                    else:
                        owner.current_tab = old_tab
            notify = getattr(owner, "notify", None)
            if callable(notify):
                notify(
                    f"agent:{name} has no record on this machine", severity="warning"
                )
            return
        if getattr(result, "status", None) not in {"found", "owner"}:
            return
        recorder = getattr(owner, "_record_link_trail", None)
        if origin is not None and callable(recorder):
            recorder(origin)
        row_name = getattr(result, "row_name", None)
        child_note = (
            f" · workflow child; showing {row_name}"
            if row_name and row_name != name
            else ""
        )
        notify = getattr(owner, "notify", None)
        if callable(notify):
            notify(
                f"{source} — {_dismissed_when(owner)}{child_note} · ⏎ restore · ctrl+o back",
                severity="information",
            )

    owner._archive_arrival_callback = arrived


def open_archive_for_archived_row(
    owner: Any,
    row: Mapping[str, Any],
    *,
    source: str,
) -> bool:
    """Open the Archive and reveal the exact selected light row."""
    from ...models.agent_archive_list import archive_row_key
    from ._archive_view import open_agents_archive_view_with_query

    _switch_to_agents(owner)
    outcome = open_agents_archive_view_with_query(
        owner,
        query="in:archive",
    )
    state = getattr(owner, "_agents_archive_view", None)
    archive = getattr(state, "archive", None)
    if archive is None or getattr(outcome, "status", None) != "opened":
        return False
    archive.reveal_row = dict(row)
    archive.selected_key = archive_row_key(row)
    archive.pending_exact_name = None
    archive.arrival_outcome = None
    notify = getattr(owner, "notify", None)
    if callable(notify):
        notify(f"{source} · opening archived run · read-only")
    return True


__all__ = [
    "_archive_name_query",
    "open_archive_for_agent",
    "open_archive_for_archived_row",
]

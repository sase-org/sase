"""Off-thread load tasks for the Memory panel.

Every function here does real disk I/O (project records, memory-directory
reads, note parsing) and must only ever run inside a worker thread, never on
the event loop -- see the TUI performance rules in ``sase/memory/tui_perf.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.memory_panel_catalog import (
    MemoryScopeRef,
    MemoryScopeSnapshot,
    build_memory_scope_ring,
    load_memory_scope_snapshot,
)
from sase.current_project import resolve_current_project


@dataclass(frozen=True, slots=True)
class MemoryPanelInitialLoad:
    """The scope ring plus the initially selected scope's snapshot."""

    ring: tuple[MemoryScopeRef, ...]
    scope_index: int
    snapshot: MemoryScopeSnapshot | None


def load_memory_panel_initial_state(
    *,
    launch_workspace: str | None,
    initial_scope_key: str | None = None,
    seed_from_current_project: bool = True,
) -> MemoryPanelInitialLoad:
    """Build the scope ring and load the initially selected snapshot.

    *initial_scope_key* selects a ring entry by key when present. Otherwise,
    when *seed_from_current_project* is set, the current project's ring entry
    is used. Failing both, the ring's first scope is used (alphabetically
    first project display name; Home is last, so it is first only when it
    is the only scope).
    """
    ring = build_memory_scope_ring(launch_workspace)
    if not ring:
        return MemoryPanelInitialLoad(ring=(), scope_index=0, snapshot=None)

    scope_index = _ring_index_for_key(ring, initial_scope_key)
    if scope_index is None and seed_from_current_project:
        try:
            current_project = resolve_current_project()
        except Exception:  # noqa: BLE001 - a seed failure must not sink the load.
            current_project = None
        if current_project is not None:
            scope_index = _ring_index_for_key(ring, current_project.project_key)
    if scope_index is None:
        scope_index = 0

    snapshot = load_memory_scope_snapshot(ring[scope_index])
    return MemoryPanelInitialLoad(
        ring=ring,
        scope_index=scope_index,
        snapshot=snapshot,
    )


def _ring_index_for_key(
    ring: tuple[MemoryScopeRef, ...], key: str | None
) -> int | None:
    if key is None:
        return None
    for index, ref in enumerate(ring):
        if ref.key == key:
            return index
    return None


__all__ = [
    "MemoryPanelInitialLoad",
    "load_memory_panel_initial_state",
]

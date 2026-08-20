"""Off-thread load tasks for the Glossary panel.

Every function here does real disk I/O (project records, ``sase.yml`` reads,
glossary compilation) and must only ever run inside a worker thread, never on
the event loop -- see the TUI performance rules in ``sase/memory/tui_perf.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.glossary_panel_catalog import (
    GlossaryProjectRef,
    GlossaryProjectSnapshot,
    build_glossary_project_ring,
    load_glossary_project_snapshot,
)
from sase.current_project import resolve_current_project


@dataclass(frozen=True, slots=True)
class GlossaryPanelInitialLoad:
    """The project ring plus the initially selected project's snapshot."""

    ring: tuple[GlossaryProjectRef, ...]
    project_index: int
    snapshot: GlossaryProjectSnapshot | None


def load_glossary_panel_initial_state(
    *,
    launch_workspace: str | None,
    initial_project_key: str | None,
    seed_from_current_project: bool = True,
    session_project_key: str | None = None,
) -> GlossaryPanelInitialLoad:
    """Build the project ring and load the initially selected snapshot.

    *initial_project_key* selects a ring entry by key when present. Otherwise
    *session_project_key* is used, then — when *seed_from_current_project* is
    set — the current project's ring entry. Failing those, the ring's first
    (alphabetically first display name) project is used.
    """
    ring = build_glossary_project_ring(launch_workspace)
    if not ring:
        return GlossaryPanelInitialLoad(ring=(), project_index=0, snapshot=None)

    project_index = _ring_index_for_key(ring, initial_project_key)
    if project_index is None:
        project_index = _ring_index_for_key(ring, session_project_key)
    if project_index is None and seed_from_current_project:
        try:
            current_project = resolve_current_project()
        except Exception:  # noqa: BLE001 - a seed failure must not sink the load.
            current_project = None
        if current_project is not None:
            project_index = _ring_index_for_key(ring, current_project.project_key)
    if project_index is None:
        project_index = 0

    snapshot = load_glossary_project_snapshot(ring[project_index])
    return GlossaryPanelInitialLoad(
        ring=ring,
        project_index=project_index,
        snapshot=snapshot,
    )


def _ring_index_for_key(
    ring: tuple[GlossaryProjectRef, ...], key: str | None
) -> int | None:
    if key is None:
        return None
    for index, ref in enumerate(ring):
        if ref.key == key:
            return index
    return None


__all__ = [
    "GlossaryPanelInitialLoad",
    "load_glossary_panel_initial_state",
]

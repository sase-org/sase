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
) -> GlossaryPanelInitialLoad:
    """Build the project ring and load the initially selected snapshot.

    *initial_project_key* selects a ring entry by key when present; otherwise
    the ring's first (alphabetically first display name) project is used.
    """
    ring = build_glossary_project_ring(launch_workspace)
    if not ring:
        return GlossaryPanelInitialLoad(ring=(), project_index=0, snapshot=None)

    project_index = 0
    if initial_project_key is not None:
        for index, ref in enumerate(ring):
            if ref.key == initial_project_key:
                project_index = index
                break

    snapshot = load_glossary_project_snapshot(ring[project_index])
    return GlossaryPanelInitialLoad(
        ring=ring,
        project_index=project_index,
        snapshot=snapshot,
    )


__all__ = [
    "GlossaryPanelInitialLoad",
    "load_glossary_panel_initial_state",
]

"""Off-thread load tasks for the Memory panel.

Every function here does real disk I/O (project records, memory-directory
reads, note parsing) and must only ever run inside a worker thread, never on
the event loop -- see the TUI performance rules in ``sase/memory/tui_perf.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.memory_panel_catalog import (
    MemoryNoteDigest,
    MemoryScopeRef,
    MemoryScopeSnapshot,
    build_memory_scope_ring,
    load_memory_scope_snapshot,
)
from sase.current_project import resolve_current_project
from sase.memory.cli_read import build_memory_read_event_for_view
from sase.memory.mutation import memory_note_digest
from sase.memory.notes import MemoryNote
from sase.memory.read_log import (
    MemoryReadEvent,
    append_memory_read_event,
    normalize_read_reason,
    require_agent_identity,
)
from sase.memory.selector import resolve_memory_selector_batch


@dataclass(frozen=True, slots=True)
class MemoryPanelInitialLoad:
    """The scope ring plus the initially selected scope's snapshot."""

    ring: tuple[MemoryScopeRef, ...]
    scope_index: int
    snapshot: MemoryScopeSnapshot | None


@dataclass(frozen=True, slots=True)
class MemoryScopeChoice:
    """One scope offered by :class:`~sase.ace.tui.modals.memory_panel_scope_picker.MemoryScopePicker`."""

    key: str
    display_name: str
    note_count: int


@dataclass(frozen=True, slots=True)
class MemoryPanelStrandRead:
    """Audit result for one Memory panel strand preview."""

    identity: str
    event: MemoryReadEvent


def load_memory_panel_initial_state(
    *,
    launch_workspace: str | None,
    initial_scope_key: str | None = None,
    session_scope_key: str | None = None,
    seed_from_current_project: bool = True,
) -> MemoryPanelInitialLoad:
    """Build the scope ring and load the initially selected snapshot.

    *initial_scope_key* selects a ring entry by key when present. Otherwise
    *session_scope_key* is used when it still exists in the ring. Otherwise,
    when *seed_from_current_project* is set, the current project's ring entry
    is used. Failing those, the ring's first scope is used (alphabetically
    first project display name; Home is last, so it is first only when it
    is the only scope). Vanished explicit or session keys fall through the
    same chain rather than failing the load.
    """
    ring = build_memory_scope_ring(launch_workspace)
    if not ring:
        return MemoryPanelInitialLoad(ring=(), scope_index=0, snapshot=None)

    scope_index = _ring_index_for_key(ring, initial_scope_key)
    if scope_index is None:
        scope_index = _ring_index_for_key(ring, session_scope_key)
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


def load_memory_scope_choices(
    ring: tuple[MemoryScopeRef, ...],
) -> tuple[MemoryScopeChoice, ...]:
    """Load every ring scope's snapshot and return its display choice.

    Only ever call this off the event loop: loading each scope reads its
    memory directory (behind the same cache :func:`load_memory_scope_snapshot`
    keeps for the panel's own scope loads).
    """
    return tuple(
        MemoryScopeChoice(
            key=ref.key,
            display_name=ref.display_name,
            note_count=len(load_memory_scope_snapshot(ref).notes),
        )
        for ref in ring
    )


def note_digest_changed(
    scope: MemoryScopeRef,
    note: MemoryNote,
    previous: MemoryNoteDigest | None,
) -> bool:
    """Return whether *note*'s on-disk bytes differ from *previous*'s digest.

    Only ever call this off the event loop: a cache miss reads the note's
    bytes from disk. Used to decide whether an external editor changed the
    note the panel had open, so the scope can be reloaded.
    """
    path = Path(scope.content_root) / note.source_relative_path
    try:
        data = path.read_bytes()
        file_stat = path.stat()
    except OSError:
        return previous is not None
    if previous is None:
        return True
    if (
        file_stat.st_mtime_ns == previous.mtime_ns
        and file_stat.st_size == previous.size
    ):
        return False
    return memory_note_digest(data) != previous.sha256


def record_memory_panel_strand_read(
    scope: MemoryScopeRef,
    *,
    web_slug: str,
    strand_slug: str,
) -> MemoryPanelStrandRead:
    """Record the audited read required before previewing a strand body.

    This is intentionally the same selector-resolution and event-building path
    as ``sase memory read``. Call it only from a worker thread.
    """
    identity = f"{web_slug}:{strand_slug}"
    reason = normalize_read_reason(f"ACE MemoryPane previewed {identity}")
    agent = require_agent_identity()
    root = Path(scope.content_root)
    view = resolve_memory_selector_batch(
        [identity],
        depth=0,
        project_root=root,
        home_root=root,
    )
    event = build_memory_read_event_for_view(
        view,
        reason=reason,
        agent=agent,
        cwd=root,
    )
    append_memory_read_event(event)
    return MemoryPanelStrandRead(identity=identity, event=event)


__all__ = [
    "MemoryPanelInitialLoad",
    "MemoryPanelStrandRead",
    "MemoryScopeChoice",
    "load_memory_panel_initial_state",
    "load_memory_scope_choices",
    "note_digest_changed",
    "record_memory_panel_strand_read",
]

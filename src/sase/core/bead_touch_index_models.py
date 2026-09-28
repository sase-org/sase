"""Shared touch-index records for the agent/bead touch index.

This module owns the wire-stable dataclasses reduced by ``sase-core``
(``bead/touch_index.rs``) plus the index filename. It imports nothing from
SASE so the store, query, and fold modules can all share it without import
cycles. Public names are re-exported through
:mod:`sase.core.bead_touch_index_facade`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TOUCH_INDEX_FILENAME = "agent_bead_touches.json"


@dataclass(frozen=True)
class BeadNotePreview:
    """One current, structured note supplied by the touch-index cache.

    The Rust reducer owns note replay and attribution.  This is deliberately
    only a tolerant wire conversion so old indexes and malformed cache rows
    degrade to no preview instead of breaking the Context card.
    """

    id: str
    author: str
    timestamp: str
    text: str
    edited_at: str | None = None
    edited_by: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class BeadTouchClose:
    """One actor's latest credited close for a bead, as reduced in core."""

    closed_at: str
    resolution: str = "done"
    reason: str = ""
    standing: bool = False


@dataclass(frozen=True)
class BeadTouch:
    """One ``(actor, bead)`` pair with aggregated verbs."""

    actor: str
    bead_id: str
    title: str = ""
    issue_type: str = ""
    status: str = ""
    verbs: dict[str, int] = field(default_factory=dict)
    first_at: str = ""
    last_at: str = ""
    read_reasons: tuple[str, ...] = ()
    current_note_count: int = 0
    note_preview: BeadNotePreview | None = None
    close: BeadTouchClose | None = None
    creation_reason: str = ""
    creation_reason_truncated: bool = False


@dataclass(frozen=True)
class BeadTouchQuery:
    """Read-only answer from the touch index file."""

    schema_version: int
    generation: str
    touches: tuple[BeadTouch, ...] = ()


@dataclass(frozen=True)
class BeadTouchRefresh:
    """Outcome of one incremental touch-index refresh."""

    schema_version: int
    generation: str
    full_rebuild: bool
    wrote: bool
    stream_count: int
    reduced_streams: tuple[str, ...] = ()
    reused_streams: int = 0
    removed_streams: tuple[str, ...] = ()
    touch_count: int = 0


@dataclass(frozen=True)
class BeadTouchIndexStatus:
    """Stat-only staleness report for the touch index."""

    schema_version: int
    state: str
    index_schema_version: int | None
    generation: str
    indexed_streams: int
    current_streams: int
    changed_streams: tuple[str, ...] = ()
    vanished_streams: tuple[str, ...] = ()


@dataclass(frozen=True)
class FoldedBeadTouch:
    """One bead folded from every contributing ``(actor, bead)`` row."""

    bead_id: str
    title: str = ""
    issue_type: str = ""
    status: str = ""
    verbs: dict[str, int] = field(default_factory=dict)
    first_at: str = ""
    last_at: str = ""
    actors: tuple[str, ...] = ()
    read_reasons: tuple[str, ...] = ()
    close: BeadTouchClose | None = None


__all__ = [
    "TOUCH_INDEX_FILENAME",
    "BeadNotePreview",
    "BeadTouch",
    "BeadTouchClose",
    "BeadTouchIndexStatus",
    "BeadTouchQuery",
    "BeadTouchRefresh",
    "FoldedBeadTouch",
]

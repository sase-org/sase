"""Merged per-bead view over touches, bead reads, and own beads."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from sase.ace.tui._bead_touches_shared import (
    BeadTouchDisplayEvent,
    parse_moment,
)
from sase.ace.tui.models.agent import Agent
from sase.core.bead_touch_index_facade import (
    BeadNotePreview,
    BeadTouch,
    BeadTouchClose,
    fold_read_reasons,
    prefer_bead_touch_close,
)

if TYPE_CHECKING:
    from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent

#: Scheme prefix marking an artifact-read ref as a bead read.
BEAD_READ_REF_PREFIX = "bead:"


@dataclass(frozen=True)
class BeadTouchEntry:
    """One bead's merged view for the panel's ``Beads:`` sub-section.

    ``verbs`` folds every contributing source: the indexed durable verbs
    plus ``read`` for audited ``bead:`` artifact reads. ``own`` marks a
    bead the agent was assigned even when it never touched it (no verbs).
    ``agent_label`` is the one session-producer label shared by the
    entry's labeled contributors; mixed-producer beads report ``None``.
    """

    bead_id: str
    title: str = ""
    verbs: dict[str, int] = field(default_factory=dict)
    first_at: str = ""
    last_at: str = ""
    own: bool = False
    agent_label: str | None = None
    read_reasons: tuple[str, ...] = ()
    current_note_count: int = 0
    note_preview: BeadNotePreview | None = None
    note_agent_label: str | None = None
    agent_close: BeadTouchClose | None = None


def _canonical_bead_id(value: str | None) -> str:
    """Return the comparison key for a bead id or ``bead:`` read ref.

    Trims whitespace and strips one ``bead:`` scheme prefix, so a
    ``bead:sase-14j.4`` read ref and the bare ``sase-14j.4`` touch id never
    split into two rows. Matching stays exact after that: no case folding
    and no suffix matching, because bead ids and agent names both use
    dotted suffixes and a loose match would cross-attribute.
    """
    text = (value or "").strip()
    if text.startswith(BEAD_READ_REF_PREFIX):
        text = text.removeprefix(BEAD_READ_REF_PREFIX).strip()
    return text


def own_bead_ids_for_agent(agent: Agent) -> tuple[str, ...]:
    """Return the bead ids the agent was assigned, in precedence order.

    Mirrors the ``_agent_bead_id`` fallback chain (explicit phase bead,
    explicit epic bead, bead id derived from a ``sase bead work`` agent
    name) but collects every distinct id instead of the first, because an
    agent assigned but never touching either bead still owns both rows.
    """
    ordered: list[str] = []
    candidates = [agent.phase_bead_id, agent.epic_bead_id, _derived_bead_id(agent)]
    for candidate in candidates:
        text = (candidate or "").strip()
        if text and text not in ordered:
            ordered.append(text)
    return tuple(ordered)


def _derived_bead_id(agent: Agent) -> str | None:
    try:
        from sase.agent.bead_display import derive_agent_bead_id_from_name

        return derive_agent_bead_id_from_name(
            agent.presented_agent_name or agent.agent_name
        )
    except Exception:
        return None


class _BeadBucket:
    """Mutable per-bead accumulator behind :func:`merge_bead_touch_entries`."""

    def __init__(self, bead_id: str) -> None:
        self.bead_id = bead_id
        self.title = ""
        self.verbs: dict[str, int] = {}
        self._moments: list[tuple[datetime, str]] = []
        self.own = False
        self._labels: set[str] = set()
        self._read_pairs: list[tuple[str, str]] = []
        self.current_note_count = 0
        self._note_ids: set[str] = set()
        self._note_candidate: (
            tuple[datetime, str, BeadNotePreview, str | None] | None
        ) = None
        self.agent_close: BeadTouchClose | None = None

    def add_verbs(self, verbs: dict[str, int]) -> None:
        for verb, count in verbs.items():
            if count > 0:
                self.verbs[verb] = self.verbs.get(verb, 0) + count

    def add_moment(self, value: str | None) -> None:
        moment = parse_moment(value)
        if moment is not None:
            self._moments.append((moment, (value or "").strip()))

    def add_title(self, title: str | None) -> None:
        cleaned = (title or "").strip()
        if not self.title and cleaned:
            self.title = cleaned

    def add_label(self, label: str | None) -> None:
        if label is not None:
            self._labels.add(label)

    def add_read_reason(self, timestamp: str | None, reason: str | None) -> None:
        self._read_pairs.append((str(timestamp or ""), str(reason or "")))

    def add_note_preview(self, touch: BeadTouch, label: str | None) -> None:
        """Fold one actor's current notes without double-counting a note ID."""
        preview = touch.note_preview
        if preview is None or not preview.id or preview.id in self._note_ids:
            return
        self._note_ids.add(preview.id)
        self.current_note_count += max(touch.current_note_count, 0)
        moment = parse_moment(preview.timestamp)
        if moment is None:
            return
        candidate = (moment, preview.id, preview, label)
        if self._note_candidate is None or candidate[:2] > self._note_candidate[:2]:
            self._note_candidate = candidate

    def add_close(self, close: BeadTouchClose | None) -> None:
        self.agent_close = prefer_bead_touch_close(self.agent_close, close)

    def entry(self) -> BeadTouchEntry:
        first_at = ""
        last_at = ""
        if self._moments:
            ordered = sorted(self._moments, key=lambda item: item[0])
            first_at = ordered[0][1]
            last_at = ordered[-1][1]
        label = next(iter(self._labels)) if len(self._labels) == 1 else None
        note_preview = None
        note_agent_label = None
        if self._note_candidate is not None:
            _, _, note_preview, note_agent_label = self._note_candidate
        return BeadTouchEntry(
            bead_id=self.bead_id,
            title=self.title,
            verbs=dict(self.verbs),
            first_at=first_at,
            last_at=last_at,
            own=self.own,
            agent_label=label,
            read_reasons=fold_read_reasons(self._read_pairs),
            current_note_count=self.current_note_count,
            note_preview=note_preview,
            note_agent_label=note_agent_label,
            agent_close=self.agent_close,
        )


def _entry_rank(entry: BeadTouchEntry) -> tuple[float, str]:
    moment = parse_moment(entry.last_at)
    epoch = moment.timestamp() if moment is not None else float("-inf")
    return (-epoch, entry.bead_id)


def merge_bead_touch_entries(
    touches: tuple[BeadTouchDisplayEvent, ...] | list[BeadTouchDisplayEvent],
    reads: tuple[ArtifactReadDisplayEvent, ...] | list[ArtifactReadDisplayEvent],
    own_bead_ids: tuple[str, ...] | list[str] = (),
) -> tuple[BeadTouchEntry, ...]:
    """Fold touches, audited bead reads, and own beads into one ranked view.

    Pure function over its three inputs so it is testable without a store:
    touch rows (durable index rows plus synthesized ``viewed`` rows from the
    machine-local view log, already ordered durable-first so durable titles
    win), the already-loaded audited artifact reads (only ``bead:`` refs
    contribute; anything else is ignored so a bead read can never
    double-list), and the agent's own bead ids. Emits one entry per
    bead with merged verb counts, the newest timestamp across all sources,
    the title from whichever source has one, and the ``own`` mark. Bead ids
    are compared after :func:`_canonical_bead_id` so a ``bead:``-prefixed ref
    and a bare id never split into two rows. Ranking is newest-touch-first
    with a bead-id tiebreak; timestamp-less own-only beads sort last.
    """
    buckets: dict[str, _BeadBucket] = {}
    own_keys = {
        key for key in (_canonical_bead_id(value) for value in own_bead_ids) if key
    }

    def bucket_for(key: str, display_id: str) -> _BeadBucket:
        bucket = buckets.get(key)
        if bucket is None:
            bucket = buckets[key] = _BeadBucket(display_id)
        return bucket

    for display in touches:
        key = _canonical_bead_id(display.touch.bead_id)
        if not key:
            continue
        bucket = bucket_for(key, display.touch.bead_id.strip())
        bucket.add_title(display.touch.title)
        bucket.add_verbs(display.touch.verbs)
        bucket.add_moment(display.touch.first_at)
        bucket.add_moment(display.touch.last_at)
        bucket.add_label(display.agent_label)
        bucket.add_note_preview(display.touch, display.agent_label)
        bucket.add_close(display.touch.close)

    for read_display in reads:
        ref = (read_display.event.ref or "").strip()
        if not ref.startswith(BEAD_READ_REF_PREFIX):
            continue
        key = _canonical_bead_id(ref)
        if not key:
            continue
        bucket = bucket_for(key, key)
        bucket.add_verbs({"read": 1})
        bucket.add_moment(read_display.event.timestamp)
        bucket.add_label(read_display.agent_label)
        bucket.add_read_reason(read_display.event.timestamp, read_display.event.reason)

    for key in own_keys:
        bucket = bucket_for(key, key)
        bucket.own = True

    return tuple(
        sorted((bucket.entry() for bucket in buckets.values()), key=_entry_rank)
    )

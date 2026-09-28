"""Per-bead folding for the agent/bead touch index.

This module owns the pure fold from ``(actor, bead)`` rows into one row per
bead, the close-preference rule shared by the fold and the Context card
merge, and the moment parsing behind both. Public names are re-exported
through :mod:`sase.core.bead_touch_index_facade`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sase.core.bead_touch_index_models import (
    BeadTouch,
    BeadTouchClose,
    FoldedBeadTouch,
)


def prefer_bead_touch_close(
    current: BeadTouchClose | None,
    candidate: BeadTouchClose | None,
) -> BeadTouchClose | None:
    """Pick a standing close over a non-standing one, else the newest."""
    if candidate is None:
        return current
    if current is None:
        return candidate
    if candidate.standing != current.standing:
        return candidate if candidate.standing else current
    candidate_moment = _parse_touch_moment(candidate.closed_at)
    current_moment = _parse_touch_moment(current.closed_at)
    if candidate_moment is None:
        return current
    if current_moment is None or candidate_moment > current_moment:
        return candidate
    return current


def canonical_bead_touch_id(value: str | None) -> str:
    """Return the per-bead fold key for a touch id or ``bead:`` read ref."""
    text = (value or "").strip()
    if text.startswith("bead:"):
        text = text.removeprefix("bead:").strip()
    return text


def _parse_touch_moment(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def fold_read_reasons(
    pairs: Sequence[tuple[str | None, str | None]],
) -> tuple[str, ...]:
    """Fold ``(timestamp, reason)`` pairs into newest-first distinct reasons.

    Pure helper: trims whitespace, drops empties, dedupes by trimmed text,
    orders newest first with undated pairs last and stable ordering.
    """
    scored: list[tuple[int, float, int, str]] = []
    for index, (timestamp, reason) in enumerate(pairs):
        cleaned = str(reason or "").strip()
        if not cleaned:
            continue
        moment = _parse_touch_moment(timestamp)
        if moment is None:
            scored.append((1, 0.0, index, cleaned))
        else:
            scored.append((0, -moment.timestamp(), index, cleaned))
    scored.sort()
    seen: set[str] = set()
    ordered: list[str] = []
    for _, _, _, cleaned in scored:
        if cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return tuple(ordered)


class _FoldBucket:
    """Mutable per-bead accumulator behind :func:`fold_touches_per_bead`."""

    def __init__(self, bead_id: str) -> None:
        self.bead_id = bead_id
        self.title = ""
        self.issue_type = ""
        self.status = ""
        self.verbs: dict[str, int] = {}
        self._moments: list[tuple[datetime, str]] = []
        self._actors: set[str] = set()
        self._read_pairs: list[tuple[str, str]] = []
        self.close: BeadTouchClose | None = None

    def add(self, touch: BeadTouch) -> None:
        actor = str(getattr(touch, "actor", "") or "").strip()
        if actor:
            self._actors.add(actor)
        title = str(getattr(touch, "title", "") or "").strip()
        if not self.title and title:
            self.title = title
        issue_type = str(getattr(touch, "issue_type", "") or "").strip()
        if not self.issue_type and issue_type:
            self.issue_type = issue_type
        status = str(getattr(touch, "status", "") or "").strip()
        if not self.status and status:
            self.status = status
        verbs = getattr(touch, "verbs", {}) or {}
        for verb, count in verbs.items():
            try:
                total = int(count)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if total > 0:
                self.verbs[str(verb)] = self.verbs.get(str(verb), 0) + total
        for moment_value in (
            str(getattr(touch, "first_at", "") or ""),
            str(getattr(touch, "last_at", "") or ""),
        ):
            moment = _parse_touch_moment(moment_value)
            if moment is not None:
                self._moments.append((moment, moment_value.strip()))
        last_at_value = str(getattr(touch, "last_at", "") or "")
        for reason in getattr(touch, "read_reasons", ()) or ():
            self._read_pairs.append((last_at_value, str(reason)))
        self.close = prefer_bead_touch_close(self.close, getattr(touch, "close", None))

    def build(self) -> FoldedBeadTouch:
        first_at = ""
        last_at = ""
        if self._moments:
            ordered = sorted(self._moments, key=lambda item: item[0])
            first_at = ordered[0][1]
            last_at = ordered[-1][1]
        return FoldedBeadTouch(
            bead_id=self.bead_id,
            title=self.title,
            issue_type=self.issue_type,
            status=self.status,
            verbs=dict(self.verbs),
            first_at=first_at,
            last_at=last_at,
            actors=tuple(sorted(self._actors)),
            read_reasons=fold_read_reasons(self._read_pairs),
            close=self.close,
        )


def fold_touches_per_bead(
    touches: Sequence[BeadTouch],
) -> list[FoldedBeadTouch]:
    """Fold ``(actor, bead)`` rows into one row per bead.

    Pure function over its input so it is testable without a store: verb
    counts sum, ``first_at`` is the earliest moment and ``last_at`` the
    newest across all contributing rows, and the title (plus ``issue_type``
    and ``status``) is the first non-empty value in input order. Callers
    pass durable index rows first so durable facts win over synthesized
    ``viewed`` and ``read`` rows; ``viewed`` never promotes to ``read``.
    Bead ids are compared after :func:`canonical_bead_touch_id` so a
    ``bead:``-prefixed ref and a bare id never split into two rows.
    """
    buckets: dict[str, _FoldBucket] = {}
    order: list[str] = []
    for touch in touches:
        key = canonical_bead_touch_id(getattr(touch, "bead_id", ""))
        if not key:
            continue
        bucket = buckets.get(key)
        if bucket is None:
            display_id = str(getattr(touch, "bead_id", "") or "").strip()
            if display_id.startswith("bead:"):
                display_id = display_id.removeprefix("bead:").strip()
            bucket = buckets[key] = _FoldBucket(display_id or key)
            order.append(key)
        bucket.add(touch)
    return [buckets[key].build() for key in order]


__all__ = [
    "canonical_bead_touch_id",
    "fold_read_reasons",
    "fold_touches_per_bead",
    "prefer_bead_touch_close",
]

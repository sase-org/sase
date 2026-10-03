"""Pin state and past-card reads for the Memory pane time travel.

Owns the ``(scope_key, selector)`` pin keys, the applied-vs-target
ordinals, and the atomic past-card paint state behind
:class:`MemoryPane`. Method calls reach the rest of the widget through
``self``; this module imports no ``_``-prefixed names from its sibling
pane modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ._memory_pane_time_shared import moment_for_card

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

#: Cap for parsed past notes per pane (FIFO eviction).
_TIME_PARSED_CACHE_SIZE = 64


@dataclass(frozen=True)
class _PastCard:
    """Everything one past-card paint needs, from a single moment."""

    applied_ordinal: int
    target_ordinal: int
    moment: Any
    body_text: str | None


def _parse_past_note(node: Any, body_text: str) -> Any | None:
    """Parse a historical body into a :class:`MemoryNote`, or ``None``."""
    try:
        from sase.memory.notes import parse_memory_note_text

        path = str(getattr(getattr(node, "note", None), "relative_path", "") or "past")
        return parse_memory_note_text(str(body_text or ""), path)
    except Exception:
        return None


class MemoryPaneTimePinsMixin(_MixinBase):
    """Pin keys, applied ordinals, and past-card reads for ``MemoryPane``."""

    if TYPE_CHECKING:
        _history_latest: dict[tuple[str, str], dict]
        _time_applied: dict[tuple[str, str], int]
        _time_bodies: dict[tuple[str, str, int], dict[str, Any]]
        _time_parsed: dict[tuple[str, str, int], Any]
        _time_pins: dict[tuple[str, str], int]

        def _history_key_for_node(
            self, node: Any | None
        ) -> tuple[str, str, Any, str] | None: ...

    def _time_key(self, node: Any | None) -> tuple[str, str] | None:
        """Return the ``(scope_key, selector)`` pin key for *node*."""
        try:
            keyed = self._history_key_for_node(node)
        except Exception:
            return None
        if keyed is None:
            return None
        return (keyed[0], keyed[1])

    def _time_pinned_ordinal(self, node: Any | None) -> int:
        """Return the target pin ordinal for *node* (0 means now)."""
        key = self._time_key(node)
        if key is None:
            return 0
        try:
            return int(self._time_pins.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _time_applied_ordinal(self, node: Any | None) -> int:
        """Return the displayed ordinal for *node* (0 means now)."""
        key = self._time_key(node)
        if key is None:
            return 0
        try:
            return int(self._time_applied.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _time_timeline(self, node: Any | None) -> dict[str, Any] | None:
        """Return the cached timeline for *node* without blocking."""
        key = self._time_key(node)
        if key is None:
            return None
        cached = self._history_latest.get(key)
        return dict(cached) if isinstance(cached, dict) else None

    def _time_subject_id(self, node: Any | None) -> str:
        """Return the band subject id for *node*."""
        try:
            wire_id = str(getattr(node, "instruction_subject", "") or "")
        except Exception:
            wire_id = ""
        if wire_id:
            return wire_id
        try:
            keyed = self._history_key_for_node(node)
            selector = keyed[1] if keyed is not None else ""
        except Exception:
            selector = ""
        try:
            from .memory_pane_time_strip import subject_id_for_selector

            is_strand = bool(getattr(node, "strand", None) is not None)
            return subject_id_for_selector(str(selector or ""), is_strand=is_strand)
        except Exception:
            return f"note:{selector}"

    def _card_moment(
        self, node: Any | None, *, applied: bool = True, view: str = "read"
    ) -> Any | None:
        """Return the kit moment for *node*'s applied (or target) pin."""
        ordinal = (
            self._time_applied_ordinal(node)
            if applied
            else self._time_pinned_ordinal(node)
        )
        if ordinal <= 0:
            return None
        return moment_for_card(
            self._time_timeline(node),
            subject_id=self._time_subject_id(node),
            pin_ordinal=ordinal,
            view=view,
        )

    def _now_moment_for_footer(
        self, node: Any | None, *, view: str = "read"
    ) -> Any | None:
        """Return the live moment for *node* so now cards show `( vN`."""
        return moment_for_card(
            self._time_timeline(node),
            subject_id=self._time_subject_id(node),
            pin_ordinal=0,
            view=view,
        )

    def _past_card_for_node(self, node: Any | None) -> _PastCard | None:
        """Return the atomic past-card state for *node*, if pinned."""
        applied = self._time_applied_ordinal(node)
        if applied <= 0:
            return None
        key = self._time_key(node)
        if key is None:
            return None
        moment = moment_for_card(
            self._time_timeline(node),
            subject_id=self._time_subject_id(node),
            pin_ordinal=applied,
        )
        if moment is None:
            return None
        wire = self._time_bodies.get((key[0], key[1], applied))
        body_text: str | None = None
        if isinstance(wire, dict):
            if bool(wire.get("body_missing")):
                body_text = "(unavailable: historical body is not stored)"
            else:
                try:
                    body_text = str(wire.get("body", "") or "")
                except Exception:
                    body_text = None
        return _PastCard(
            applied_ordinal=applied,
            target_ordinal=self._time_pinned_ordinal(node),
            moment=moment,
            body_text=body_text,
        )

    def _time_past_note(self, node: Any, body_text: str) -> Any | None:
        """Return the parsed past note for *node*, memoized per version."""
        key = self._time_key(node)
        if key is None:
            return None
        cache_key = (key[0], key[1], self._time_applied_ordinal(node))
        cached = self._time_parsed.get(cache_key)
        if cached is not None:
            return cached
        parsed = _parse_past_note(node, body_text)
        if parsed is None:
            return None
        self._time_parsed[cache_key] = parsed
        while len(self._time_parsed) > _TIME_PARSED_CACHE_SIZE:
            try:
                self._time_parsed.pop(next(iter(self._time_parsed)))
            except StopIteration:
                break
        return parsed


__all__ = ["MemoryPaneTimePinsMixin"]

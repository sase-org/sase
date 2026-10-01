"""Per-section history state for ``PagerScreen``.

Owns the history generation counter, pin rehydration, and pin-ordinal
accessors. Discovery, stepping, and swap logic live in the sibling
``_screen_history_*`` modules; this module never imports them.
"""

from __future__ import annotations

from typing import Any

from sase.pager.document import PagerDocument, PagerSection
from sase.pager.history.models import SectionTimeState, VersionPin

__all__ = ["PagerHistoryStateMixin"]


class PagerHistoryStateMixin:
    """Own per-section history state and pin accessors."""

    document: PagerDocument
    _history_states: dict[str, SectionTimeState]
    _history_generation: int
    _history_pending: dict[str, str]
    _history_supported: dict[str, bool]
    _history_indexing: bool
    _history_coalesced: bool

    def _init_history_state(self: Any) -> None:
        self._history_states = {}
        self._history_generation = 0
        self._history_pending = {}
        self._history_supported = {}
        self._history_indexing = False
        self._history_coalesced = False

    def _bump_history_generation(self: Any) -> None:
        self._history_generation += 1

    def _rehydrate_history_pins(
        self: Any, pins: tuple[tuple[str, object], ...]
    ) -> None:
        self._history_generation += 1
        for identity, pin in pins:
            state = self._history_states.get(identity)
            if state is None:
                continue
            state.generation = self._history_generation
            if isinstance(pin, VersionPin):
                state.current_pin = pin

    def _history_state_for(self: Any, section: PagerSection) -> SectionTimeState | None:
        return self._history_states.get(section.identity)

    def _history_current_pin_ordinal(self: Any, section: PagerSection) -> int:
        state = self._history_states.get(section.identity)
        if state is not None and state.current_pin is not None:
            return state.current_pin.ordinal
        pin = section.version_pin
        if pin is not None:
            return pin.ordinal
        return 0

    def _history_current_pin_ordinal_for_identity(self: Any, identity: str) -> int:
        state = self._history_states.get(identity)
        if state is not None and state.current_pin is not None:
            return state.current_pin.ordinal
        for section in self.document.sections:
            if section.identity == identity and section.version_pin is not None:
                return section.version_pin.ordinal
        return 0

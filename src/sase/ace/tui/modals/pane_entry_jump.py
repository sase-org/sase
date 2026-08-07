"""Shared adaptive entry-jump state machine for Admin Center panes and modals.

Every Admin Center working tab binds ``'`` to an adaptive hint jump over that
tab's selectable rows.  The state machine behind that key -- hint allocation,
the pending-prefix matcher, and the bounded back stack -- is identical on every
tab, so it lives here once and each pane supplies four small host hooks that
describe its own row list.

Modals whose rows are addressed by an opaque key rather than a position use
:class:`KeyedPaneEntryJumpMixin`, which keeps the same one state machine and
translates between that key space and the mixin's logical-index space.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field

from ..actions.navigation.jump_hints import (
    JumpHintMatchOutcome,
    build_jump_hint_maps,
    match_jump_hint,
)
from .saved_agent_group_revival_rendering import apply_jump_hint_prefix

JUMP_BACK_STACK_LIMIT = 10


@dataclass
class _JumpState:
    """Mutable jump-mode state for a single pane instance."""

    mode_active: bool = False
    pending_prefix: str = ""
    hint_to_index: dict[str, int] = field(default_factory=dict)
    index_to_hint: dict[int, str] = field(default_factory=dict)
    back_stack: list[int] = field(default_factory=list)

    def clear_hints(self) -> None:
        """Drop hint mode and every allocated hint, keeping the back stack."""
        self.mode_active = False
        self.pending_prefix = ""
        self.hint_to_index = {}
        self.index_to_hint = {}


class PaneEntryJumpMixin:
    """Adaptive ``'`` entry-jump behavior for a pane with a logical row list.

    Hosts implement the four ``_jump_*`` hooks below.  Indices passed through
    this mixin are positions in the pane's *logical* row list, never raw
    ``OptionList`` indices, so panes that interleave disabled group headers map
    logical index to widget index inside ``_jump_select_index``.
    """

    # Created lazily so the mixin needs no ``__init__`` and cannot perturb a
    # pane's Textual MRO.  Only the immutable ``None`` sentinel is shared.
    _pane_jump_state: _JumpState | None = None

    # -- host hooks ---------------------------------------------------------

    def _jump_target_count(self) -> int:
        """Return how many rows are currently jumpable."""
        raise NotImplementedError

    def _jump_current_index(self) -> int | None:
        """Return the currently selected logical row index, if any."""
        raise NotImplementedError

    def _jump_select_index(self, index: int) -> None:
        """Move the selection to ``index`` through the pane's own path."""
        raise NotImplementedError

    def _jump_repaint(self) -> None:
        """Rebuild the pane's rows and refresh its hint line."""
        raise NotImplementedError

    # -- host-facing API ----------------------------------------------------

    @property
    def jump_mode_active(self) -> bool:
        """Whether hint jump mode is currently painted on this pane."""
        return self._jump_state().mode_active

    @property
    def jump_back_stack(self) -> list[int]:
        """The bounded stack of pre-jump row indices, oldest first."""
        return list(self._jump_state().back_stack)

    def jump_hint_for(self, index: int) -> str | None:
        """Return the hint to prefix onto logical row ``index``, if any."""
        state = self._jump_state()
        if not state.mode_active:
            return None
        return state.index_to_hint.get(index)

    def action_jump_to_entry(self) -> None:
        """Enter adaptive jump mode over this pane's current rows."""
        indices = list(range(self._jump_target_count()))
        if not indices:
            return
        hint_to_index, index_to_hint = build_jump_hint_maps(indices)
        if not hint_to_index:
            return

        state = self._jump_state()
        state.hint_to_index = hint_to_index
        state.index_to_hint = index_to_hint
        state.pending_prefix = ""
        state.mode_active = True
        self._jump_repaint()

    def handle_jump_key(self, key: str) -> bool:
        """Consume ``key`` while jump mode is active; return whether it was."""
        state = self._jump_state()
        if not state.mode_active:
            return False
        if key == "escape":
            self.exit_jump_mode()
            return True

        push_current = True
        if key == "apostrophe":
            target_count = self._jump_target_count()
            while state.back_stack:
                previous_index = state.back_stack.pop()
                if 0 <= previous_index < target_count:
                    return self._perform_jump(previous_index, push_current=False)
            target_index = next(iter(state.hint_to_index.values()), None)
        else:
            match = match_jump_hint(state.hint_to_index, state.pending_prefix, key)
            if match.outcome is JumpHintMatchOutcome.PENDING:
                state.pending_prefix = match.prefix
                return True
            if match.outcome is JumpHintMatchOutcome.INVALID:
                self.exit_jump_mode()
                return True
            target_index = match.target
            state.pending_prefix = ""

        if target_index is None:
            self.exit_jump_mode()
            return True
        return self._perform_jump(target_index, push_current=push_current)

    def clear_jump_hints(self) -> None:
        """Leave jump mode without repainting or touching the back stack."""
        self._jump_state().clear_hints()

    def exit_jump_mode(self) -> None:
        """Leave jump mode and repaint the rows without moving the selection."""
        self.clear_jump_hints()
        self._jump_repaint()

    def invalidate_jump_hints(
        self, *, identities_changed: bool, target_count: int
    ) -> None:
        """Apply the stale-data rule after the pane's rows were rebuilt.

        Changed row identities invalidate the back stack as well as the hints,
        because the stored indices no longer name the same rows.  Unchanged
        identities only drop the hints, and only when one of them now points
        outside the row range.
        """
        state = self._jump_state()
        if identities_changed:
            state.clear_hints()
            state.back_stack = []
            return
        if state.mode_active and not self._jump_hints_are_valid(target_count):
            state.clear_hints()

    # -- internals ----------------------------------------------------------

    def _jump_state(self) -> _JumpState:
        """Return this instance's jump state, creating it on first use."""
        state = self._pane_jump_state
        if state is None:
            state = _JumpState()
            self._pane_jump_state = state
        return state

    def _jump_hints_are_valid(self, target_count: int) -> bool:
        return all(
            0 <= index < target_count
            for index in self._jump_state().hint_to_index.values()
        )

    def _perform_jump(self, target_index: int, *, push_current: bool) -> bool:
        state = self._jump_state()
        if not 0 <= target_index < self._jump_target_count():
            self.exit_jump_mode()
            return True

        current_index = self._jump_current_index()
        if push_current and current_index is not None and current_index != target_index:
            state.back_stack.append(current_index)
            del state.back_stack[:-JUMP_BACK_STACK_LIMIT]

        self.clear_jump_hints()
        self._jump_select_index(target_index)
        return True


class KeyedPaneEntryJumpMixin[K: Hashable](PaneEntryJumpMixin):
    """Entry jump for hosts that name their rows by key instead of position.

    Several modals identify a row by an opaque key -- a notification index into
    an unsorted list, an ``OptionList`` option id -- rather than by its position
    among the jumpable rows.  This adapter keeps the single state machine in
    :class:`PaneEntryJumpMixin` and does the key/logical-index translation in
    one place, so hosts only describe their rows in their own terms.
    """

    # -- host hooks ---------------------------------------------------------

    def _jump_target_keys(self) -> list[K]:
        """Return the keys of the currently jumpable rows, in visual order."""
        raise NotImplementedError

    def _jump_current_key(self) -> K | None:
        """Return the key of the currently selected row, if any."""
        raise NotImplementedError

    def _jump_select_key(self, key: K) -> None:
        """Move the selection to ``key`` through the host's own path."""
        raise NotImplementedError

    # -- host-facing API ----------------------------------------------------

    def jump_hints_by_key(self) -> dict[K, str]:
        """Return the hint to render on each keyed row while jump mode is on."""
        hints: dict[K, str] = {}
        for index, key in enumerate(self._jump_target_keys()):
            hint = self.jump_hint_for(index)
            if hint is not None:
                hints[key] = hint
        return hints

    # -- PaneEntryJumpMixin hooks -------------------------------------------

    def _jump_target_count(self) -> int:
        return len(self._jump_target_keys())

    def _jump_current_index(self) -> int | None:
        current = self._jump_current_key()
        if current is None:
            return None
        keys = self._jump_target_keys()
        return keys.index(current) if current in keys else None

    def _jump_select_index(self, index: int) -> None:
        keys = self._jump_target_keys()
        if 0 <= index < len(keys):
            self._jump_select_key(keys[index])


__all__ = [
    "JUMP_BACK_STACK_LIMIT",
    "KeyedPaneEntryJumpMixin",
    "PaneEntryJumpMixin",
    "apply_jump_hint_prefix",
]

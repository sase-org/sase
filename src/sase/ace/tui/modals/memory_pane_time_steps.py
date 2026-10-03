"""Step actions for the Memory pane time travel.

Owns the ``(`` ``)`` ``{`` ``}`` card-stepping intents behind
:class:`MemoryPane`: resolving the destination from the pager's moment
model, recording pending intents while indexing, and applying the pin.
Method calls reach the rest of the widget through ``self``; this module
imports no ``_``-prefixed names from its sibling pane modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._memory_pane_time_shared import moment_for_card

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


def _step_destination(moment: Any, intent: str) -> int | None:
    """Return the destination ordinal for *intent*, or ``None``.

    ``None`` means a boundary: the key has nowhere to go. Never raises.
    """
    try:
        from sase.pager.history_kit import step_target

        return step_target(moment, intent)  # type: ignore[arg-type]
    except Exception:
        return None


def _step_boundary_notice(moment: Any, intent: str) -> str:
    """Return the pager's boundary notice for a refused step."""
    try:
        from sase.pager.history_kit import boundary_notice

        return str(boundary_notice(moment, intent))  # type: ignore[arg-type]
    except Exception:
        return "Already at the oldest version."


class MemoryPaneTimeStepsMixin(_MixinBase):
    """Step intents and pin application for ``MemoryPane``."""

    if TYPE_CHECKING:
        _history_failed: set[tuple[str, str]]
        _time_applied: dict[tuple[str, str], int]
        _time_pending: dict[tuple[str, str], str]
        _time_pins: dict[tuple[str, str], int]

        def _apply_time_pin(
            self, key: tuple[str, str], node: Any, ordinal: int
        ) -> None: ...
        def _ensure_history_load(self, scope_key: str, selector: str) -> None: ...
        def _ensure_time_body(
            self, key: tuple[str, str], node: Any, ordinal: int
        ) -> bool: ...
        def _prefetch_time_bodies(
            self, node: Any, timeline: dict[str, Any], *, center_ordinal: int
        ) -> None: ...
        def _render_note_card(self) -> None: ...
        def _selected_row(self) -> Any | None: ...
        def _time_key(self, node: Any | None) -> tuple[str, str] | None: ...
        def _time_pinned_ordinal(self, node: Any | None) -> int: ...
        def _time_subject_id(self, node: Any | None) -> str: ...
        def _time_timeline(self, node: Any | None) -> dict[str, Any] | None: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...

    def _step_time_pin(self, intent: str) -> None:
        """Step the current card along *intent* (``older``/``newer``/… )."""
        from sase.ace.tui.util.trace import tui_trace

        with tui_trace("memory.history.step", intent=intent):
            node = self._selected_row()
            key = self._time_key(node)
            if node is None or key is None:
                return
            timeline = self._time_timeline(node)
            if timeline is None:
                if key in self._history_failed:
                    self.notify(
                        "history unavailable for this selection", severity="error"
                    )
                    return
                # Indexing: record the intent (last wins) and apply it
                # when the timeline lands (§5.4 rule 6).
                self._time_pending[key] = intent
                try:
                    self._ensure_history_load(key[0], key[1])
                except Exception:
                    pass
                return
            moment = moment_for_card(
                timeline,
                subject_id=self._time_subject_id(node),
                pin_ordinal=self._time_pinned_ordinal(node),
            )
            if moment is None:
                self.notify("No history to step through.", severity="warning")
                return
            self._apply_step_intent(key, node, timeline, moment, intent)

    def _apply_step_intent(
        self,
        key: tuple[str, str],
        node: Any,
        timeline: dict[str, Any],
        moment: Any,
        intent: str,
    ) -> None:
        """Apply one step intent against a loaded timeline and moment."""
        destination = _step_destination(moment, intent)
        if destination is None:
            self.notify(_step_boundary_notice(moment, intent), severity="warning")
            return
        if int(destination) == 0:
            self._time_pins.pop(key, None)
            self._time_applied.pop(key, None)
            self._time_pending.pop(key, None)
            self._render_note_card()
            self._prefetch_time_bodies(node, timeline, center_ordinal=0)
            return
        self._time_pins[key] = int(destination)
        self._time_pending.pop(key, None)
        if not self._ensure_time_body(key, node, int(destination)):
            # Cache miss: the previous version stays on screen with a
            # ``loading vN…`` strip until the worker lands (last wins).
            self._render_note_card()
        else:
            self._apply_time_pin(key, node, int(destination))

    def action_history_older(self) -> None:
        """Step the card to the older version."""
        self._step_time_pin("older")

    def action_history_newer(self) -> None:
        """Step the card to the newer version."""
        self._step_time_pin("newer")

    def action_history_first(self) -> None:
        """Step the card to the first version."""
        self._step_time_pin("first")

    def action_history_now(self) -> None:
        """Return the card to now."""
        self._step_time_pin("now")


__all__ = ["MemoryPaneTimeStepsMixin"]

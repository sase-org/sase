"""Past-body loads, arrival freshness, and pin guards for time travel.

Owns the off-thread past-body fetches (last-wins generation guard),
the atomic pin apply, neighbour prefetch, arrival re-resolution, scope
invalidation, and the Esc/past-edit guards behind :class:`MemoryPane`.
Method calls reach the rest of the widget through ``self``; this module
imports no ``_``-prefixed names from its sibling pane modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from ._memory_pane_time_shared import moment_for_card

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object

#: Toast shown when a mutation key is pressed while pinned in the past.
PIN_EDIT_REFUSAL = "leave the past to edit · } now"

#: Cap for memoized past bodies per pane (FIFO eviction).
_TIME_BODY_CACHE_SIZE = 256


class MemoryPaneTimeBodiesMixin(_MixinBase):
    """Body loads, arrival freshness, and guards for ``MemoryPane``."""

    if TYPE_CHECKING:
        _closed: bool
        _history_failed: set[tuple[str, str]]
        _history_latest: dict[tuple[str, str], dict]
        _loading: bool
        _time_applied: dict[tuple[str, str], int]
        _time_bodies: dict[tuple[str, str, int], dict[str, Any]]
        _time_generation: int
        _time_parsed: dict[tuple[str, str, int], Any]
        _time_pending: dict[tuple[str, str], str]
        _time_pins: dict[tuple[str, str], int]
        _time_prefetched_key: tuple[str, str] | None
        _time_request: tuple[str, str, int, int] | None
        _time_worker: Worker[tuple[str, str, int, int, dict | None]] | None
        app: Any
        is_mounted: bool

        def _ace_history(self) -> Any | None: ...
        def _apply_step_intent(
            self,
            key: tuple[str, str],
            node: Any,
            timeline: dict[str, Any],
            moment: Any,
            intent: str,
        ) -> None: ...
        def _ensure_history_load(self, scope_key: str, selector: str) -> None: ...
        def _history_key_for_node(
            self, node: Any | None
        ) -> tuple[str, str, Any, str] | None: ...
        def _render_note_card(self) -> None: ...
        def _selected_row(self) -> Any | None: ...
        def _time_key(self, node: Any | None) -> tuple[str, str] | None: ...
        def _time_applied_ordinal(self, node: Any | None) -> int: ...
        def _time_pinned_ordinal(self, node: Any | None) -> int: ...
        def _time_subject_id(self, node: Any | None) -> str: ...
        def _time_timeline(self, node: Any | None) -> dict[str, Any] | None: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Worker: ...  # type: ignore[override]

    def _remember_time_body(
        self, key: tuple[str, str], ordinal: int, wire: dict[str, Any]
    ) -> None:
        """Memoize one version wire, evicting oldest first when full."""
        self._time_bodies[(key[0], key[1], int(ordinal))] = wire
        while len(self._time_bodies) > _TIME_BODY_CACHE_SIZE:
            try:
                self._time_bodies.pop(next(iter(self._time_bodies)))
            except StopIteration:
                break

    def _ensure_time_body(self, key: tuple[str, str], node: Any, ordinal: int) -> bool:
        """Start a worker for a missing past body; True when cached."""
        if (key[0], key[1], int(ordinal)) in self._time_bodies:
            return True
        try:
            keyed = self._history_key_for_node(node)
            ref = keyed[2] if keyed is not None else None
        except Exception:
            ref = None
        if ref is None:
            return False
        self._time_generation += 1
        generation = self._time_generation
        version_arg = f"v{int(ordinal)}"
        self._time_request = (key[0], key[1], int(ordinal), generation)

        def task() -> tuple[str, str, int, int, dict | None]:
            try:
                from .memory_panel_history import selector_for_node

                history = self._ace_history()
                if history is None:
                    return (key[0], key[1], int(ordinal), generation, None)
                scope = history.scope_for_ref(ref)
                if scope is None:
                    return (key[0], key[1], int(ordinal), generation, None)
                wire = history.version_body(scope, selector_for_node(node), version_arg)
                return (
                    key[0],
                    key[1],
                    int(ordinal),
                    generation,
                    dict(wire) if isinstance(wire, dict) else None,
                )
            except Exception:
                return (key[0], key[1], int(ordinal), generation, None)

        try:
            self._time_worker = self.run_worker(
                task,
                thread=True,
                exclusive=True,
                group="memory-panel-time-body",
                exit_on_error=False,
            )
        except Exception:
            return False
        return False

    def _on_time_body_state_changed(self, event: Any) -> None:
        """Apply a landed past body only when it is still the target."""
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 5:
            return
        scope_key, selector, ordinal, generation, wire = result
        key = (scope_key, selector)
        if self._time_request != (scope_key, selector, int(ordinal), generation):
            return  # Stale: a newer step already won.
        self._time_request = None
        if not isinstance(wire, dict):
            # Fail-open: drop the pin and say so (§5.4 rule 4).
            self._time_pins.pop(key, None)
            self._time_applied.pop(key, None)
            self.notify("past body unavailable · back at now", severity="warning")
            if self._closed or not self.is_mounted:
                return
            try:
                self._render_note_card()
            except Exception:
                pass
            return
        self._remember_time_body(key, int(ordinal), wire)
        if self._time_pins.get(key, 0) != int(ordinal):
            return  # The user stepped elsewhere meanwhile.
        node = self._selected_row()
        if node is None or self._time_key(node) != key:
            return  # Stale: the selection moved before this load landed.
        self._apply_time_pin(key, node, int(ordinal))

    def _apply_time_pin(self, key: tuple[str, str], node: Any, ordinal: int) -> None:
        """Atomically show *ordinal*: pill, strip, frame, body, footer."""
        self._time_applied[key] = int(ordinal)
        if self._closed or not self.is_mounted:
            return
        try:
            self._render_note_card()
        except Exception:
            pass
        try:
            timeline = self._time_timeline(node)
            if timeline is not None:
                self._prefetch_time_bodies(node, timeline, center_ordinal=int(ordinal))
        except Exception:
            pass

    def _prefetch_time_bodies(
        self, node: Any, timeline: dict[str, Any], *, center_ordinal: int
    ) -> None:
        """Fetch the nearest two older/newer bodies off-thread (§5.4.6)."""
        key = self._time_key(node)
        if key is None or self._loading:
            return
        try:
            from sase.pager.history_kit import visible_ordinals_for_timeline

            visible = [int(v) for v in visible_ordinals_for_timeline(timeline)]
        except Exception:
            return
        if not visible:
            return
        center = int(center_ordinal) if int(center_ordinal) > 0 else max(visible) + 1
        ordered = sorted(visible)
        older = [v for v in ordered if v < center][-2:]
        newer = [v for v in ordered if v > center][:2]
        missing = [
            v for v in (*older, *newer) if (key[0], key[1], v) not in self._time_bodies
        ]
        if not missing:
            return
        try:
            keyed = self._history_key_for_node(node)
            ref = keyed[2] if keyed is not None else None
        except Exception:
            ref = None
        if ref is None:
            return
        try:
            from .memory_panel_history import selector_for_node

            selector = selector_for_node(node)
        except Exception:
            return

        def task() -> None:
            try:
                history = self._ace_history()
                if history is None:
                    return
                scope = history.scope_for_ref(ref)
                if scope is None:
                    return
                for ordinal in missing:
                    if self._closed:
                        return
                    cache_key = (key[0], key[1], int(ordinal))
                    if cache_key in self._time_bodies:
                        continue
                    try:
                        wire = history.version_body(scope, selector, f"v{int(ordinal)}")
                    except Exception:
                        continue
                    if isinstance(wire, dict):
                        self._remember_time_body(key, int(ordinal), wire)
            except Exception:
                pass

        try:
            self.run_worker(
                task,
                thread=True,
                exclusive=True,
                group="memory-panel-time-prefetch",
                exit_on_error=False,
            )
        except Exception:
            pass

    def _maybe_prefetch_at_now(self, node: Any | None) -> None:
        """Prefetch neighbours once per selection while at now."""
        if node is None or self._time_pinned_ordinal(node) > 0:
            return
        key = self._time_key(node)
        if key is None or key == self._time_prefetched_key:
            return
        timeline = self._time_timeline(node)
        if timeline is None:
            return
        self._time_prefetched_key = key
        try:
            self._prefetch_time_bodies(node, timeline, center_ordinal=0)
        except Exception:
            pass

    def _after_history_landed(self, scope_key: str, selector: str) -> None:
        """Re-resolve the pin, apply pending steps, prefetch at now."""
        key = (scope_key, selector)
        summary = self._history_latest.get(key)
        if not isinstance(summary, dict):
            return
        node = self._selected_row()
        if node is None or self._time_key(node) != key:
            return
        try:
            self._reresolve_time_pin(key, node, summary)
        except Exception:
            pass
        pending = self._time_pending.pop(key, None)
        if pending is not None:
            try:
                moment = moment_for_card(
                    summary,
                    subject_id=self._time_subject_id(node),
                    pin_ordinal=self._time_pinned_ordinal(node),
                )
                if moment is None:
                    self.notify("No history to step through.", severity="warning")
                else:
                    self._apply_step_intent(key, node, summary, moment, pending)
                    return
            except Exception:
                pass
        try:
            self._maybe_prefetch_at_now(node)
        except Exception:
            pass

    def _reresolve_time_pin(
        self, key: tuple[str, str], node: Any, timeline: dict[str, Any]
    ) -> None:
        """Hold the pin across index rebuilds (§5.2 rule 5).

        The pin re-resolves by commit and blob; ``N newer`` updates come
        free with the new timeline. A vanished version returns to now
        with a toast.
        """
        pinned = int(self._time_pins.get(key, 0) or 0)
        if pinned <= 0:
            return
        rows = timeline.get("versions", ())
        match: dict[str, Any] | None = None
        if isinstance(rows, (list, tuple)):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    if int(row.get("ordinal", 0) or 0) == pinned:
                        match = row
                        break
                except (TypeError, ValueError):
                    continue
        if match is None:
            self._time_pins.pop(key, None)
            self._time_applied.pop(key, None)
            self.notify("that version is gone · back at now", severity="warning")
            try:
                self._render_note_card()
            except Exception:
                pass

    def _drop_time_state_for_scope(self, scope_key: str) -> None:
        """Forget pins, bodies, and intents after scope invalidation."""
        pin_key: tuple[str, str]
        for pin_key in [key for key in self._time_pins if key[0] == scope_key]:
            self._time_pins.pop(pin_key, None)
        for pin_key in [key for key in self._time_applied if key[0] == scope_key]:
            self._time_applied.pop(pin_key, None)
        for pin_key in [key for key in self._time_pending if key[0] == scope_key]:
            self._time_pending.pop(pin_key, None)
        body_key: tuple[str, str, int]
        for body_key in [key for key in self._time_bodies if key[0] == scope_key]:
            self._time_bodies.pop(body_key, None)
        for body_key in [key for key in self._time_parsed if key[0] == scope_key]:
            self._time_parsed.pop(body_key, None)
        if (
            self._time_prefetched_key is not None
            and self._time_prefetched_key[0] == scope_key
        ):
            self._time_prefetched_key = None

    def _time_unpin_if_pinned(self) -> bool:
        """Return to now when pinned; True when the rung was consumed."""
        node = self._selected_row()
        if node is None or self._time_applied_ordinal(node) <= 0:
            return False
        key = self._time_key(node)
        if key is not None:
            self._time_pins.pop(key, None)
            self._time_applied.pop(key, None)
            self._time_pending.pop(key, None)
        try:
            self._render_note_card()
        except Exception:
            pass
        return True

    def _refuse_while_pinned(self) -> bool:
        """Toast the past-edit refusal; True when the key must stop."""
        node = self._selected_row()
        applied = self._time_applied_ordinal(node) if node is not None else 0
        if applied <= 0:
            return False
        self.notify(PIN_EDIT_REFUSAL, severity="warning")
        return True

    def _refuse_link_while_pinned(self) -> bool:
        """Toast the past-link refusal; True when the key must stop."""
        node = self._selected_row()
        applied = self._time_applied_ordinal(node) if node is not None else 0
        if applied <= 0:
            return False
        self.notify(
            f"links are as of now · H follows them at v{applied}",
            severity="warning",
        )
        return True

    def _history_initial_revision(self) -> str:
        """Return the pager revision for the card's exact pin (``H``)."""
        try:
            applied = self._time_applied_ordinal(self._selected_row())
        except Exception:
            applied = 0
        return f"v{int(applied)}" if int(applied) > 0 else "now"


__all__ = ["PIN_EDIT_REFUSAL", "MemoryPaneTimeBodiesMixin"]

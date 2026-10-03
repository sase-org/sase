"""Timeline lens highlight, preview, and pin stepping (``@`` lens)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


class MemoryPaneTimelineLensPreviewMixin(_MixinBase):
    """Lens cursor motion with the 150 ms card debouncer."""

    if TYPE_CHECKING:
        _debouncer: Any | None
        _selection_guard: Any
        _time_applied: dict[tuple[str, str], int]
        _time_bodies: dict[Any, Any]
        _time_diff_view: bool
        _time_pending: dict[tuple[str, str], str]
        _time_pins: dict[tuple[str, str], int]
        _timeline_cursor: int
        _timeline_listed: tuple[dict[str, Any], ...]
        _timeline_preview_pending: bool
        _timeline_scheduled: int
        _timeline_subject_node: Any | None

        def _apply_time_pin(
            self, key: tuple[str, str], node: Any, ordinal: int
        ) -> None: ...
        def _ensure_time_body(
            self, key: tuple[str, str], node: Any, ordinal: int
        ) -> bool: ...
        def _lens_is_timeline(self) -> bool: ...
        def _note_list(self) -> Any: ...
        def _render_timeline_rail(self) -> None: ...
        def _repaint_timeline_rows(self, *indices: int) -> None: ...
        def _time_applied_ordinal(self, node: Any | None) -> int: ...
        def _time_key(self, node: Any | None) -> tuple[str, str] | None: ...
        def _time_pinned_ordinal(self, node: Any | None) -> int: ...
        def _timeline_cursor_row(self) -> dict[str, Any] | None: ...
        def _timeline_ordinal_for_row(
            self, row: dict[str, Any] | None
        ) -> int | None: ...
        def _timeline_row_index_for_ordinal(self, ordinal: int) -> int: ...

    # --- highlight, preview, stale drops ----------------------------------

    def on_option_list_option_highlighted(self, event: Any) -> None:
        """Route rail motion to the lens cursor; Notes falls through.

        Textual invokes every ``on_*`` override along the MRO, so the
        lens branch stops the event to keep the Notes handler from
        treating a version highlight as a subject change; outside the
        lens this handler does nothing and the Notes handler runs once.
        """
        if not self._lens_is_timeline():
            return
        try:
            event.prevent_default()
            event.stop()
        except Exception:
            pass
        try:
            from .memory_panel_state import _NOTE_LIST_ID  # noqa: PLC0415

            if getattr(event.option_list, "id", None) != _NOTE_LIST_ID:
                return
            idx = int(event.option_index)
        except Exception:
            return
        listed = tuple(getattr(self, "_timeline_listed", ()))
        summary_index = len(listed)
        if not 0 <= idx <= summary_index:
            return
        try:
            current = self._note_list().highlighted
            current = int(current) if current is not None else idx
        except Exception:
            current = idx
        try:
            guard = self._selection_guard
            if guard is not None and guard.should_ignore(
                f"timeline:{idx}",
                idx,
                current_identity=f"timeline:{current}",
                current_row=current,
            ):
                return
        except Exception:
            pass
        if idx == summary_index:
            return  # The hidden-summary row holds the pin, it moves nothing.
        previous = int(getattr(self, "_timeline_cursor", 0) or 0)
        self._timeline_cursor = idx
        self._timeline_scheduled = idx
        try:
            row = listed[idx] if 0 <= idx < len(listed) else None
            ordinal = self._timeline_ordinal_for_row(
                dict(row) if isinstance(row, dict) else None
            )
            needs_load = False
            if ordinal is not None and int(ordinal) > 0:
                node = getattr(self, "_timeline_subject_node", None)
                key = self._time_key(node)
                if key is not None and (key[0], key[1], int(ordinal)) not in getattr(
                    self, "_time_bodies", {}
                ):
                    needs_load = True
            self._timeline_preview_pending = bool(needs_load)
            if previous != idx:
                self._repaint_timeline_rows(previous, idx)
        except Exception:
            pass
        try:
            debouncer = self._debouncer
            if debouncer is not None:
                debouncer.schedule(self._timeline_preview_fire)
            else:
                self._timeline_preview_fire()
        except Exception:
            pass

    def _timeline_preview_fire(self) -> None:
        """Apply the scheduled lens cursor to the card (last wins)."""
        if not self._lens_is_timeline():
            return
        cursor = int(getattr(self, "_timeline_cursor", 0) or 0)
        if cursor != int(getattr(self, "_timeline_scheduled", -1) or -1):
            return  # A newer motion already won.
        row = self._timeline_cursor_row()
        ordinal = self._timeline_ordinal_for_row(row)
        if ordinal is None:
            return
        node = getattr(self, "_timeline_subject_node", None)
        if node is None:
            return
        key = self._time_key(node)
        if key is None:
            return
        if int(ordinal) <= 0:
            self._timeline_preview_pending = False
            try:
                self._time_pins.pop(key, None)
                self._time_applied.pop(key, None)
                self._time_pending.pop(key, None)
            except Exception:
                pass
            try:
                self._render_note_card()
            except Exception:
                pass
            return
        try:
            self._time_pins[key] = int(ordinal)
            self._time_pending.pop(key, None)
        except Exception:
            pass
        try:
            if self._ensure_time_body(key, node, int(ordinal)):
                self._timeline_preview_pending = False
                self._apply_time_pin(key, node, int(ordinal))
            else:
                self._render_note_card()
        except Exception:
            pass

    def _render_note_card(self) -> None:
        """Render the card, then settle the lens rail's pending marker."""
        try:
            from .memory_panel_view import (  # noqa: PLC0415
                MemoryPanelViewMixin,
            )

            MemoryPanelViewMixin._render_note_card(self)  # type: ignore[arg-type]
        except Exception:
            return
        if not self._lens_is_timeline():
            return
        try:
            node = getattr(self, "_timeline_subject_node", None)
            applied = int(self._time_applied_ordinal(node) or 0)
            cursor_row = self._timeline_cursor_row()
            cursor_ordinal = self._timeline_ordinal_for_row(cursor_row)
            settled = cursor_ordinal is None or int(cursor_ordinal) == applied
            if settled and bool(getattr(self, "_timeline_preview_pending", False)):
                self._timeline_preview_pending = False
                self._render_timeline_rail()
        except Exception:
            pass

    def _timeline_sync_cursor_to_pin(self) -> None:
        """Move the lens cursor onto the card's pin after a step key."""
        if not self._lens_is_timeline():
            return
        try:
            node = getattr(self, "_timeline_subject_node", None)
            pinned = int(self._time_pinned_ordinal(node) or 0)
        except (TypeError, ValueError):
            return
        except Exception:
            return
        try:
            index = self._timeline_row_index_for_ordinal(pinned)
        except Exception:
            return
        self._timeline_cursor = index
        self._timeline_scheduled = index
        self._timeline_preview_pending = False
        try:
            option_list = self._note_list()
            guard = self._selection_guard
            if guard is not None:
                try:
                    guard.prepare(f"timeline:{index}", index)
                except Exception:
                    pass
            listed = tuple(getattr(self, "_timeline_listed", ()))
            if 0 <= index < len(listed):
                option_list.highlighted = index
        except Exception:
            pass

    def _step_time_pin(self, intent: str) -> None:
        """Step the card, then carry the lens cursor with the pin."""
        try:
            from .memory_pane_time import MemoryPaneTimeMixin  # noqa: PLC0415

            MemoryPaneTimeMixin._step_time_pin(self, intent)  # type: ignore[arg-type]
        except Exception:
            return
        try:
            self._timeline_sync_cursor_to_pin()
        except Exception:
            pass


__all__ = [
    "MemoryPaneTimelineLensPreviewMixin",
]

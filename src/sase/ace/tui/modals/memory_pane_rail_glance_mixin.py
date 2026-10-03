"""Rail recency glance and deleted subjects (phase rail-glance).

Owns the phase rail-glance Notes rail behind :class:`MemoryPane`: a
right-aligned newest-change glyph and age on every Notes rail row,
built off-thread from one ``subjects()`` plus one ``feed()`` per
scope load, and a ``D`` toggle listing tombstoned subjects in a
trailing ``DELETED`` group with read-only tombstone cards.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.worker import Worker, WorkerState

from ._memory_pane_rail_glance_shared import DeletedSubject
from .memory_pane_rail_glance_feed import (
    build_recency_map,
    collect_deleted_subjects,
    subject_displays,
)
from .memory_pane_rail_glance_rendering import (
    build_deleted_row_text,
    glance_glyph_only,
    glance_suffix,
    history_only_node,
    is_promotion_class,
    node_glance_path,
)

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase

    from sase.ace.tui.memory_panel_catalog import MemoryRailNode
else:
    _MixinBase = object

#: Toast when ``D`` finds no deleted subjects to list.
_NO_DELETED_TOAST = "no deleted subjects in this scope"


class MemoryPaneRailGlanceMixin(_MixinBase):
    """Recency glance loads, the ``D`` DELETED toggle, tombstone pins."""

    if TYPE_CHECKING:
        _closed: bool
        _current_note: str | None
        _deleted_subjects: tuple[DeletedSubject, ...]
        _filter_bodies: bool
        _filter_text: str
        _glance_failed: bool
        _glance_generation: int
        _glance_map: dict[str, tuple[str, int]]
        _glance_worker: Worker[tuple[str, dict, tuple, str | None, int]] | None
        _keymaps: Any
        _lens: Any
        _loading: bool
        _ring: tuple[Any, ...]
        _rows: tuple[Any, ...]
        _scope_index: int
        _show_deleted: bool
        _time_pins: dict[tuple[str, str], int]
        _time_request: Any | None
        app: Any
        is_mounted: bool

        def _ace_history(self) -> Any | None: ...
        def _apply_filter(
            self, pattern: str, *, include_bodies: bool, preferred_note: str | None
        ) -> None: ...
        def _ensure_history_load(self, scope_key: str, selector: str) -> None: ...
        def _ensure_time_body(
            self, key: tuple[str, str], node: Any, ordinal: int
        ) -> bool: ...
        def _history_key_for_node(self, node: Any | None) -> Any | None: ...
        def _lens_name(self) -> Any: ...
        def _resize_note_rail(self) -> None: ...
        def _selected_row(self) -> Any | None: ...
        def _time_applied_ordinal(self, node: Any | None) -> int: ...
        def _time_key(self, node: Any | None) -> tuple[str, str] | None: ...
        def _time_pinned_ordinal(self, node: Any | None) -> int: ...
        def _time_timeline(self, node: Any | None) -> dict[str, Any] | None: ...
        def _update_footer(self) -> None: ...
        def _update_header(self) -> None: ...
        def notify(self, *args: Any, **kwargs: Any) -> Any: ...
        def run_worker(self, *args: Any, **kwargs: Any) -> Any: ...

    # --- hooks overriding the state-mixin defaults ----------------------

    def _note_row_glance(self, node: Any) -> tuple[str, str, bool]:
        """Return ``(full, glyph, promoted)`` for one rail row, or blanks."""
        try:
            path = node_glance_path(node)
        except Exception:
            return ("", "", False)
        if not path:
            return ("", "", False)
        try:
            hit = self._glance_map.get(path)
        except Exception:
            return ("", "", False)
        if hit is None:
            return ("", "", False)
        class_name, moment = hit
        try:
            full = glance_suffix(str(class_name), int(moment))
        except Exception:
            return ("", "", False)
        if not full:
            return ("", "", False)
        return (
            full,
            glance_glyph_only(str(class_name)),
            is_promotion_class(class_name),
        )

    def _glance_column_width(self) -> int:
        """Return the widest full glance suffix (0 omits the column)."""
        try:
            entries = list(self._glance_map.values())
        except Exception:
            return 0
        if not entries:
            return 0
        try:
            import time as _now

            now_epoch = int(_now.time())
            widest = 0
            for class_name, moment in entries:
                suffix = glance_suffix(
                    str(class_name), int(moment), now_epoch=now_epoch
                )
                widest = max(widest, Text(suffix).cell_len if suffix else 0)
            return int(widest)
        except Exception:
            return 0

    def _deleted_filter_matches(self, pattern: str) -> tuple[MemoryRailNode, ...]:
        """Return DELETED rows matching *pattern* (by path), in feed order."""
        if not self._show_deleted:
            return ()
        try:
            subjects = tuple(self._deleted_subjects)
        except Exception:
            return ()
        if not subjects:
            return ()
        needle = str(pattern or "").strip().casefold()
        rows: list[MemoryRailNode] = []
        for subject in subjects:
            try:
                if needle and needle not in str(subject.path).casefold():
                    continue
                rows.append(history_only_node(subject))
            except Exception:
                continue
        return tuple(rows)

    def _deleted_header_count(self) -> int:
        """Return the header's ``N deleted`` count (0 hides the chip)."""
        try:
            if not self._show_deleted:
                return 0
            return len(self._deleted_subjects)
        except Exception:
            return 0

    def _history_only_option(self, node: Any) -> Any | None:
        """Return the ``✖ name   deleted 3w`` option for a DELETED row."""
        try:
            path = str(getattr(getattr(node, "note", None), "relative_path", "") or "")
            identity = str(getattr(node, "identity", "") or path)
        except Exception:
            return None
        if not path:
            return None
        display = ""
        moment = 0
        try:
            for subject in tuple(self._deleted_subjects):
                if str(subject.path) == path:
                    display = str(subject.display or "")
                    moment = int(subject.committer_time or 0)
                    break
        except Exception:
            pass
        if not display:
            try:
                display = Path(path).stem or path
            except Exception:
                display = path
        try:
            from textual.widgets.option_list import Option  # noqa: PLC0415

            return Option(
                build_deleted_row_text(display, int(moment or 0)), id=identity
            )
        except Exception:
            return None

    # --- scope lifecycle --------------------------------------------------

    def _apply_snapshot(self, snapshot: Any, *, preferred_note: str | None) -> None:
        """Apply the scope snapshot, then rebuild the glance off-thread."""
        try:
            super()._apply_snapshot(snapshot, preferred_note=preferred_note)  # type: ignore[misc]
        except Exception:
            pass
        try:
            self._start_glance_load()
        except Exception:
            pass

    def _start_glance_load(self) -> None:
        """Build the recency map plus DELETED list in a thread worker."""
        try:
            ring = self._ring
            scope_index = int(self._scope_index)
            ref = ring[scope_index]
            scope_key = str(getattr(ref, "key", "") or "")
        except Exception:
            return
        if not scope_key:
            return
        history = self._ace_history()
        if history is None:
            return
        try:
            scope = history.scope_for_ref(ref)
        except Exception:
            return
        if scope is None:
            return
        self._glance_generation = int(getattr(self, "_glance_generation", 0) or 0) + 1
        generation = self._glance_generation
        worker = getattr(self, "_glance_worker", None)
        try:
            if worker is not None and not worker.is_finished:
                worker.cancel()
        except Exception:
            pass

        def task() -> tuple[str, dict, tuple, str | None, int]:
            try:
                subjects = history.subjects(scope)
            except Exception as exc:
                return (scope_key, {}, (), f"subjects: {exc}", generation)
            try:
                feed = history.feed([scope])
            except Exception as exc:
                return (scope_key, {}, (), f"feed: {exc}", generation)
            try:
                recency = build_recency_map(feed)
                deleted = collect_deleted_subjects(
                    feed, displays=subject_displays(subjects)
                )
            except Exception as exc:
                return (scope_key, {}, (), f"map: {exc}", generation)
            return (scope_key, recency, deleted, None, generation)

        try:
            self._glance_worker = self.run_worker(
                task,
                thread=True,
                exclusive=True,
                group="memory-panel-glance",
                exit_on_error=False,
            )
        except Exception:
            pass

    def _on_glance_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply a landed glance map only when it is still current."""
        if event.state != WorkerState.SUCCESS:
            if event.state == WorkerState.CANCELLED:
                return
            # Fail-open: omit the column and keep the rail (§5.4 rule 4).
            try:
                self._glance_failed = True
            except Exception:
                pass
            return
        result = event.worker.result
        if not isinstance(result, tuple) or len(result) != 5:
            return
        scope_key, recency, deleted, error, generation = result
        try:
            if int(generation) != int(getattr(self, "_glance_generation", 0) or 0):
                return  # Stale: a newer scope load already won.
            current_key = self._ring[self._scope_index].key
            if str(current_key) != str(scope_key):
                return
        except Exception:
            return
        if self._closed or not self.is_mounted:
            return
        if error is not None or not isinstance(recency, dict):
            try:
                self._glance_failed = True
            except Exception:
                pass
            return
        try:
            self._glance_map = dict(recency)
            self._deleted_subjects = tuple(deleted)
            self._glance_failed = False
            if not self._deleted_subjects:
                self._show_deleted = False
        except Exception:
            return
        # Rows paint first and gain the column when the map lands; the
        # rail width is recomputed once here. Inside a lens the Notes
        # rail stays frozen.
        try:
            if self._lens_name() != "notes":
                return
        except Exception:
            pass
        try:
            self._resize_note_rail()
        except Exception:
            pass
        try:
            self._apply_filter(
                self._filter_text,
                include_bodies=self._filter_bodies,
                preferred_note=self._current_note,
            )
        except Exception:
            pass
        try:
            self._update_header()
        except Exception:
            pass
        try:
            self._update_footer()
        except Exception:
            pass

    # --- D toggle ---------------------------------------------------------

    def action_toggle_deleted(self) -> None:
        """Toggle the trailing DELETED group of tombstoned subjects."""
        try:
            if self._lens_name() != "notes":
                return  # Lenses own the rail while open.
        except Exception:
            pass
        if self._loading:
            return
        try:
            if self._show_deleted:
                self._show_deleted = False
            else:
                if not self._deleted_subjects:
                    self.notify(_NO_DELETED_TOAST)
                    return
                self._show_deleted = True
        except Exception:
            return
        try:
            self._resize_note_rail()
        except Exception:
            pass
        try:
            self._apply_filter(
                self._filter_text,
                include_bodies=self._filter_bodies,
                preferred_note=self._current_note,
            )
        except Exception:
            pass
        try:
            self._update_header()
        except Exception:
            pass
        try:
            self._update_footer()
        except Exception:
            pass

    # --- tombstone cards ----------------------------------------------------

    def _is_history_only(self, node: Any | None) -> bool:
        """Return whether *node* is a history-only (deleted) row."""
        try:
            return bool(node is not None and getattr(node, "history_only", False))
        except Exception:
            return False

    def _ensure_tombstone_state(self, node: Any | None) -> None:
        """Pin a history-only row to its deletion so the card is a tombstone.

        The existing past-card machinery then renders the ``✖ DELETED``
        pill, the deleted frame, the tombstone strip row, and the last
        content; ``(``/``{`` step older and ``@``/``H`` keep working.
        Idempotent: cached pins and bodies short-circuit. Never raises.
        """
        if not self._is_history_only(node):
            return
        try:
            ordinal = int(getattr(node, "deleted_ordinal", 0) or 0)
        except (TypeError, ValueError):
            return
        if ordinal <= 0:
            return
        try:
            key = self._time_key(node)
        except Exception:
            return
        if key is None:
            return
        try:
            if self._time_pinned_ordinal(node) <= 0:
                self._time_pins[key] = int(ordinal)
        except Exception:
            pass
        try:
            if self._time_applied_ordinal(node) > 0:
                return
        except Exception:
            pass
        try:
            pending = getattr(self, "_time_request", None)
            if (
                isinstance(pending, tuple)
                and len(pending) == 4
                and pending[0] == key[0]
                and pending[1] == key[1]
                and int(pending[2]) == int(ordinal)
            ):
                return
        except Exception:
            pass
        try:
            timeline = self._time_timeline(node)
        except Exception:
            timeline = None
        if timeline is None:
            try:
                self._ensure_history_load(key[0], key[1])
            except Exception:
                pass
            return
        try:
            self._ensure_time_body(key, node, int(ordinal))
        except Exception:
            pass

    def _set_rows(self, nodes: Any, *, preferred_note: str | None) -> None:
        """Apply rail rows, then pin a selected tombstone to its deletion.

        The Timeline lens re-skins ``_render_note_card`` outside the
        MRO chain, so tombstone pins hook the selection paths (which
        always repaint the card) instead of the render itself.
        """
        try:
            super()._set_rows(nodes, preferred_note=preferred_note)  # type: ignore[misc]
        except Exception:
            pass
        try:
            self._ensure_tombstone_state(self._selected_row())
        except Exception:
            pass

    def on_option_list_option_highlighted(self, event: Any) -> None:
        """Pin a newly highlighted tombstone (Notes rail only)."""
        # Textual dispatches ``on_*`` along the whole MRO, so this also
        # fires inside the lenses, where the Notes selection is frozen.
        try:
            if self._lens_name() != "notes":  # type: ignore[attr-defined]
                return
        except Exception:
            pass
        try:
            self._ensure_tombstone_state(self._selected_row())
        except Exception:
            pass

    def _after_history_landed(self, scope_key: str, selector: str) -> None:
        """Resolve the pin, then ensure a tombstone body when selected."""
        try:
            super()._after_history_landed(scope_key, selector)  # type: ignore[misc]
        except Exception:
            pass
        try:
            self._ensure_tombstone_state(self._selected_row())
        except Exception:
            pass


__all__ = ["MemoryPaneRailGlanceMixin"]

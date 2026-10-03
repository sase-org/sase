"""Rail entry, rendering, and cursor routing for the Changes lens."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ._memory_pane_changes_shared import CHANGES_ROW_PREFIX, MORE_ROW_ID
from .memory_pane_lens import LENS_CHANGES, LENS_NOTES
from .memory_pane_review import changeset_is_unreviewed, entries_by_scope

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
else:
    _MixinBase = object


#: Rail width bounds mirror the Notes rail (see
#: ``sase.ace.tui.modals.memory_panel_rendering``).
_CHANGES_RAIL_MIN_WIDTH = 32
_CHANGES_RAIL_MAX_WIDTH = 52


class MemoryPaneChangesRailMixin(_MixinBase):
    """Turn the Notes rail into day-grouped changesets and route motion."""

    if TYPE_CHECKING:
        _changes_all_scopes: bool
        _changes_cursor: int
        _changes_failed: tuple[str, ...]
        _changes_feed: dict[str, Any] | None
        _changes_filter: str
        _changes_generation: int
        _changes_limit: int
        _changes_listed: tuple[dict[str, Any], ...]
        _changes_loading: bool
        _changes_mark_worker: Any | None
        _changes_older: int
        _changes_review: tuple[Any, ...]
        _changes_scheduled: int
        _changes_scope_label: str
        _changes_sections: dict[tuple[str, str, str], str]
        _changes_section_failed: set[tuple[str, str, str]]
        _changes_total: int
        _changes_worker: Any | None
        _current_note: str | None
        _debouncer: Any | None
        _filter_text: str
        _lens: Any
        _lens_snapshot: Any | None
        _loading: bool
        _ring: tuple[Any, ...]
        _rows: tuple[Any, ...]
        _scope_index: int
        _selection_guard: Any
        app: Any
        is_mounted: bool
        from textual.widgets import OptionList as _OptionList  # noqa: F401

        def _ace_history(self) -> Any | None: ...
        def _changes_cursor_row(self) -> dict[str, Any] | None: ...
        def _changes_fetch(self) -> None: ...
        def _changes_rebuild_rows(self) -> None: ...
        def _lens_name(self) -> Any: ...
        def _lens_take_notes_snapshot(self, node: Any | None) -> Any: ...
        def _note_list(self) -> _OptionList: ...
        def query_one(self, *args: Any, **kwargs: Any) -> Any: ...
        def _render_note_card(self) -> None: ...
        def _selected_row(self) -> Any | None: ...
        def _update_footer(self) -> None: ...
        def _update_header(self) -> None: ...

    # --- guards ---------------------------------------------------------

    def _lens_is_changes(self) -> bool:
        """Return whether the rail currently shows the Changes lens."""
        try:
            return self._lens_name() == LENS_CHANGES
        except Exception:
            return False

    # --- entry / exit ---------------------------------------------------

    def action_open_changes(self) -> None:
        """Toggle the Changes lens from Notes; inert inside Timeline."""
        try:
            lens = self._lens_name()
        except Exception:
            lens = LENS_NOTES
        if lens == LENS_CHANGES:
            self._lens_exit_to_notes()
            return
        if lens != LENS_NOTES:
            return  # The other lens key is inert inside a lens (D3).
        self._changes_enter()

    def _changes_enter(self) -> None:
        """Turn the rail into day-grouped changesets for the scope."""
        from sase.ace.tui.util.trace import tui_trace  # noqa: PLC0415

        with tui_trace("memory.history.lens_open", lens="changes"):
            try:
                node = self._selected_row()
            except Exception:
                node = None
            try:
                self._lens_snapshot = self._lens_take_notes_snapshot(node)
            except Exception:
                self._lens_snapshot = None
            try:
                self._lens = LENS_CHANGES
            except Exception:
                pass
            self._changes_all_scopes = False
            self._changes_filter = ""
            self._changes_limit = 100
            self._changes_cursor = 0
            self._changes_scheduled = -1
            self._changes_generation = (
                int(getattr(self, "_changes_generation", 0) or 0) + 1
            )
            self._changes_sections = {}
            self._changes_section_failed = set()
            self._changes_feed = None
            self._changes_listed = ()
            self._changes_loading = True
            self._changes_review = ()
            try:
                self._render_changes_rail()
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
            self._changes_fetch()

    def _lens_exit_to_notes(self) -> None:
        """Restore Notes from the Changes lens; delegate other lenses onward."""
        try:
            lens = self._lens_name()
        except Exception:
            lens = LENS_NOTES
        if lens != LENS_CHANGES:
            try:
                super()._lens_exit_to_notes()  # type: ignore[misc]
            except Exception:
                try:
                    from .memory_pane_lens import (  # noqa: PLC0415
                        MemoryPaneLensMixin as _Framework,
                    )

                    snapshot = getattr(self, "_lens_snapshot", None)
                    self._lens = LENS_NOTES
                    self._lens_snapshot = None
                    _Framework._lens_restore_notes_snapshot(self, snapshot)  # type: ignore[arg-type]
                except Exception:
                    pass
            return
        snapshot = getattr(self, "_lens_snapshot", None)
        self._changes_clear_state()
        try:
            self._lens = LENS_NOTES
        except Exception:
            pass
        try:
            self._lens_snapshot = None
        except Exception:
            pass
        try:
            from .memory_pane_lens import MemoryPaneLensMixin  # noqa: PLC0415

            MemoryPaneLensMixin._lens_restore_notes_snapshot(self, snapshot)  # type: ignore[arg-type]
        except Exception:
            pass

    def _changes_clear_state(self) -> None:
        """Forget lens rows, cursor, filter, window, and section cache."""
        for attr, value in (
            ("_changes_feed", None),
            ("_changes_listed", ()),
            ("_changes_cursor", 0),
            ("_changes_scheduled", -1),
            ("_changes_filter", ""),
            ("_changes_limit", 100),
            ("_changes_all_scopes", False),
            ("_changes_failed", ()),
            ("_changes_scope_label", ""),
            ("_changes_total", 0),
            ("_changes_older", 0),
            ("_changes_loading", False),
            ("_changes_sections", {}),
            ("_changes_section_failed", set()),
            # The review watermark survives a mark worker: clearing the
            # lens must never cancel the off-thread persist. The worker
            # repaints only while the lens is still open.
            ("_changes_review", ()),
        ):
            try:
                setattr(self, attr, value)
            except Exception:
                pass
        try:
            worker = getattr(self, "_changes_worker", None)
            if worker is not None and not worker.is_finished:
                worker.cancel()
        except Exception:
            pass

    # --- rail rendering ---------------------------------------------------

    def _render_changes_rail(self) -> None:
        """Paint the lens rows into the Notes rail widget."""
        try:
            option_list = self._note_list()
        except Exception:
            return
        listed = tuple(getattr(self, "_changes_listed", ()) or ())
        try:
            cursor = int(getattr(self, "_changes_cursor", 0) or 0)
        except (TypeError, ValueError):
            cursor = 0
        try:
            from sase.memory.history.feed_model import (  # noqa: PLC0415
                changeset_row_text,
                older_window_text,
                regen_count_text,
            )
        except Exception:
            return
        options: list[Option] = []
        try:
            review_indexed = entries_by_scope(
                tuple(getattr(self, "_changes_review", ()) or ())
            )
        except Exception:
            review_indexed = {}
        try:
            dot_accent = str(getattr(self, "_accent", "") or "")
        except Exception:
            dot_accent = ""
        for row in listed:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("kind", "") or "")
            if kind == "day":
                title = str(row.get("title", "") or "")
                options.append(
                    Option(
                        Text(f"━ {title} ━", style="dim"),
                        id=str(row.get("id", "") or None),
                        disabled=True,
                    )
                )
            elif kind == "changeset":
                view = row.get("view")
                if view is None:
                    line = ""
                else:
                    try:
                        line = changeset_row_text(view)
                    except Exception:
                        line = ""
                try:
                    dotted = view is not None and changeset_is_unreviewed(
                        view, review_indexed
                    )
                except Exception:
                    dotted = False
                if dotted:
                    prompt = Text()
                    prompt.append(
                        "● ",
                        style=f"bold {dot_accent}" if dot_accent else "bold",
                    )
                    prompt.append(line or "(changeset)")
                    options.append(Option(prompt, id=str(row.get("id", "") or None)))
                else:
                    options.append(
                        Option(
                            Text(line or "(changeset)"),
                            id=str(row.get("id", "") or None),
                        )
                    )
            elif kind == "regen":
                try:
                    count = int(row.get("count", 0) or 0)
                except (TypeError, ValueError):
                    count = 0
                options.append(
                    Option(
                        Text(regen_count_text(count), style="dim"),
                        id=str(row.get("id", "") or None),
                        disabled=True,
                    )
                )
            elif kind == "more":
                try:
                    older = int(row.get("older", 0) or 0)
                except (TypeError, ValueError):
                    older = 0
                options.append(
                    Option(
                        Text(older_window_text(older), style="dim"),
                        id=MORE_ROW_ID,
                    )
                )
        if not options:
            try:
                loading = bool(getattr(self, "_changes_loading", False))
            except Exception:
                loading = False
            options.append(
                Option(
                    Text(
                        "loading changes…"
                        if loading
                        else "(no memory changes in this window)",
                        style="dim",
                    ),
                    id=f"{CHANGES_ROW_PREFIX}empty",
                    disabled=True,
                )
            )
        try:
            guard = self._selection_guard
        except Exception:
            guard = None
        try:
            option_list.clear_options()
            option_list.add_options(options)
            if options:
                target = max(0, min(cursor, len(options) - 1))
                if guard is not None:
                    try:
                        guard.prepare(f"changes:{target}", target)
                    except Exception:
                        pass
                option_list.highlighted = target
        except Exception:
            pass
        try:
            self._resize_changes_rail()
        except Exception:
            pass

    def _resize_changes_rail(self) -> None:
        """Pin the rail to its maximum width in the Changes lens."""
        try:
            from textual.containers import Horizontal  # noqa: PLC0415

            body = self.query_one("#memory-panel-body", Horizontal)
            note_list = self._note_list()
            available = int(body.size.width or 0)
        except Exception:
            return
        width = _CHANGES_RAIL_MAX_WIDTH
        if available > 0:
            room = available - 56 - 1
            width = min(width, max(_CHANGES_RAIL_MIN_WIDTH, room))
        width = max(_CHANGES_RAIL_MIN_WIDTH, width)
        try:
            current = note_list.styles.width
            if current is not None and current.is_cells and int(current.value) == width:
                return
            note_list.styles.width = width
        except Exception:
            pass

    # --- highlight, preview, stale drops ----------------------------------

    def on_option_list_option_highlighted(self, event: Any) -> None:
        """Route rail motion to the lens cursor; Notes falls through."""
        if not self._lens_is_changes():
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
        listed = tuple(getattr(self, "_changes_listed", ()) or ())
        if not 0 <= idx < len(listed):
            return
        try:
            current = self._note_list().highlighted
            current = int(current) if current is not None else idx
        except Exception:
            current = idx
        try:
            guard = self._selection_guard
            if guard is not None and guard.should_ignore(
                f"changes:{idx}",
                idx,
                current_identity=f"changes:{current}",
                current_row=current,
            ):
                return
        except Exception:
            pass
        row = listed[idx] if isinstance(listed[idx], dict) else None
        kind = str((row or {}).get("kind", "") or "")
        if kind == "more":
            self._changes_cursor = idx
            self._changes_extend_window()
            return
        if kind != "changeset":
            return  # Day and regen rows hold the card; they move nothing.
        self._changes_cursor = idx
        self._changes_scheduled = idx
        try:
            debouncer = self._debouncer
            if debouncer is not None:
                debouncer.schedule(self._changes_preview_fire)
            else:
                self._changes_preview_fire()
        except Exception:
            pass

    def _changes_preview_fire(self) -> None:
        """Apply the scheduled lens cursor to the card (last wins)."""
        if not self._lens_is_changes():
            return
        try:
            cursor = int(getattr(self, "_changes_cursor", 0) or 0)
            scheduled = int(getattr(self, "_changes_scheduled", -1) or -1)
        except (TypeError, ValueError):
            return
        if cursor != scheduled:
            return  # A newer motion already won.
        try:
            self._render_note_card()
        except Exception:
            pass

    def _changes_extend_window(self) -> None:
        """Extend the bounded window by 100 when the cursor hits the tail."""
        try:
            older = int(getattr(self, "_changes_older", 0) or 0)
        except (TypeError, ValueError):
            older = 0
        if older <= 0:
            return
        try:
            self._changes_limit = int(getattr(self, "_changes_limit", 100) or 100) + 100
        except (TypeError, ValueError):
            self._changes_limit = 200
        try:
            keep = self._changes_cursor_row()
            keep_key = None
            if isinstance(keep, dict) and keep.get("kind") == "changeset":
                view = keep.get("view")
                keep_key = (getattr(view, "scope_key", ""), getattr(view, "commit", ""))
            self._changes_rebuild_rows()
            if keep_key is not None:
                for index, row in enumerate(
                    tuple(getattr(self, "_changes_listed", ()))
                ):
                    if not isinstance(row, dict) or row.get("kind") != "changeset":
                        continue
                    view = row.get("view")
                    if (
                        getattr(view, "scope_key", ""),
                        getattr(view, "commit", ""),
                    ) == keep_key:
                        self._changes_cursor = index
                        break
            self._render_changes_rail()
            self._update_header()
        except Exception:
            pass


__all__ = [
    "MemoryPaneChangesRailMixin",
]

"""Widget updates for the Memory panel's header, footer, trail, and card.

Everything here writes already-built renderables from
:mod:`sase.ace.tui.modals.memory_panel_rendering` into the panel's mounted
widgets; the pure text builders themselves live in that module.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import RenderableType
from rich.text import Text
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Markdown, Static

from .glossary_panel_rendering import build_trail_strip
from .memory_panel_rendering import (
    build_diagnostics_message,
    build_empty_scope_message,
    build_empty_scope_no_root_message,
    build_no_match_message,
    build_note_card_meta,
    build_note_card_title,
    build_note_description,
    build_panel_footer,
    build_panel_header,
    note_rail_width,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
    from textual.widgets import OptionList

    from sase.ace.tui.keymaps import MemoryPanelKeymaps
    from sase.ace.tui.memory_panel_catalog import (
        MemoryRailNode,
        MemoryScopeRef,
        MemoryScopeSnapshot,
    )
    from sase.memory.notes import MemoryNote
else:
    _MixinBase = object


class MemoryPanelViewMixin(_MixinBase):
    """Header, footer, trail, and note-card rendering."""

    if TYPE_CHECKING:
        _accent: str
        _all_rows: tuple[MemoryRailNode, ...]
        _chip_cursor: int | None
        _chip_notes: tuple[MemoryNote, ...]
        _chip_parent_count: int
        _current_note: str | None
        _filter_text: str
        _keymaps: MemoryPanelKeymaps
        _loading: bool
        _rows: tuple[MemoryRailNode, ...]
        _ring: tuple[MemoryScopeRef, ...]
        _scope_index: int
        _snapshot: MemoryScopeSnapshot | None
        _trail: list[str]

        def _note_list(self) -> OptionList: ...

        def _scope_is_unpublished(self) -> bool: ...

        def _selected_is_writable(self) -> bool: ...

        def _selected_row(self) -> MemoryRailNode | None: ...

    def _loading_header_text(self) -> Text:
        return Text("MEMORY  ·  loading…", style=f"bold {self._accent}")

    def _update_header(self) -> None:
        header: RenderableType
        if self._loading:
            header = self._loading_header_text()
        else:
            scope_display_name = (
                self._snapshot.scope.display_name if self._snapshot else ""
            )
            header = build_panel_header(
                scope_display_name=scope_display_name,
                note_count=len(self._all_rows),
                scope_index=self._scope_index,
                scope_count=len(self._ring),
                accent=self._accent,
                unpublished=self._scope_is_unpublished(),
            )
        self.query_one("#memory-panel-header", Static).update(header)

    def _resize_note_rail(self) -> None:
        """Fit the note rail to its widest row within the panel's width."""
        try:
            body = self.query_one("#memory-panel-body", Horizontal)
            note_list = self._note_list()
        except NoMatches:
            return
        generated_paths = (
            self._snapshot.generated_paths
            if self._snapshot is not None
            else frozenset()
        )
        width = note_rail_width(
            self._all_rows,
            generated_paths=generated_paths,
            available_width=body.size.width,
        )
        current = note_list.styles.width
        if current is not None and current.is_cells and int(current.value) == width:
            return
        note_list.styles.width = width

    def _update_footer(self) -> None:
        node = self._selected_row()
        focused_link_stem = None
        if self._chip_cursor is not None and 0 <= self._chip_cursor < len(
            self._chip_notes
        ):
            focused_link_stem = self._chip_notes[self._chip_cursor].path.stem
        footer = build_panel_footer(
            self._keymaps,
            has_notes=bool(self._rows),
            has_source_path=node is not None,
            ring_size=len(self._ring),
            has_links=bool(self._chip_notes),
            has_trail=bool(self._trail),
            focused_link_stem=focused_link_stem,
            can_mutate=self._selected_is_writable(),
            unpublished=self._scope_is_unpublished(),
        )
        footer_widget = self.query_one("#memory-panel-footer", Static)
        footer_widget.update(footer)
        footer_widget.display = bool(footer)

    def _trail_strip(self) -> Static:
        return self.query_one("#memory-panel-trail", Static)

    def _update_trail_strip(self) -> None:
        trail_widget = self._trail_strip()
        if not self._trail or self._current_note is None:
            trail_widget.display = False
            trail_widget.update("")
            return
        trail_widget.display = True
        labels = tuple(Path(path).stem for path in (*self._trail, self._current_note))
        trail_widget.update(build_trail_strip(labels, accent=self._accent))

    def _render_note_card(self) -> None:
        self._update_trail_strip()
        title_widget = self.query_one("#memory-panel-card-title", Static)
        description_widget = self.query_one("#memory-panel-card-description", Static)
        body_widget = self.query_one("#memory-panel-card-body", Markdown)
        meta_widget = self.query_one("#memory-panel-card-meta", Static)

        if self._loading:
            title_widget.update("")
            description_widget.update("")
            body_widget.update("Loading…")
            meta_widget.update("")
            return

        snapshot = self._snapshot
        if snapshot is None or not self._ring:
            title_widget.update("")
            description_widget.update("")
            body_widget.update("No memory scopes are available.")
            meta_widget.update("")
            return

        if snapshot.diagnostics:
            title_widget.update("")
            description_widget.update("")
            body_widget.update("")
            meta_widget.update(
                build_diagnostics_message(snapshot.diagnostics, accent=self._accent)
            )
            return

        if not snapshot.notes:
            title_widget.update("")
            description_widget.update("")
            body_widget.update("")
            if snapshot.scope.memory_read_root is None:
                meta_widget.update(
                    build_empty_scope_no_root_message(
                        snapshot.scope.display_name, accent=self._accent
                    )
                )
            else:
                meta_widget.update(
                    build_empty_scope_message(
                        snapshot.scope.display_name, accent=self._accent
                    )
                )
            return

        node = self._selected_row()
        if node is None:
            title_widget.update("")
            description_widget.update("")
            body_widget.update("")
            if self._filter_text:
                meta_widget.update(build_no_match_message(self._filter_text))
            else:
                meta_widget.update("")
            return

        note = node.note
        title_widget.update(
            build_note_card_title(
                note,
                scope_display_name=snapshot.scope.display_name,
                accent=self._accent,
            )
        )
        description_widget.update(build_note_description(note))
        body_widget.update(note.body if note.body.strip() else "_No body content._")
        parent = self._chip_notes[: self._chip_parent_count]
        children = self._chip_notes[self._chip_parent_count :]
        focused_link_number = (
            self._chip_cursor + 1 if self._chip_cursor is not None else None
        )
        meta_widget.update(
            build_note_card_meta(
                snapshot,
                note,
                accent=self._accent,
                parent=parent,
                children=children,
                focused_link_number=focused_link_number,
            )
        )


__all__ = ["MemoryPanelViewMixin"]

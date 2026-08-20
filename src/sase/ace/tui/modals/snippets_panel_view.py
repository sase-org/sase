"""Widget updates for the Snippets panel's header, footer, trail, and card.

Everything here writes already-built renderables from
:mod:`sase.ace.tui.modals.snippets_panel_rendering` into the panel's mounted
widgets; the pure text builders themselves live in that module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import RenderableType
from rich.text import Text
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Static

from .snippets_panel_rendering import (
    build_composed_section,
    build_diagnostics_message,
    build_empty_project_message,
    build_no_match_message,
    build_panel_footer,
    build_panel_header,
    build_raw_section,
    build_snippet_card_meta,
    build_snippet_card_title,
    build_trail_strip,
    trigger_rail_width,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
    from textual.widgets import OptionList

    from sase.ace.tui.keymaps import SnippetPanelKeymaps
    from sase.ace.tui.snippets_panel_catalog import (
        SnippetProjectRef,
        SnippetProjectSnapshot,
    )
    from sase.snippet.models import SnippetEntry
else:
    _MixinBase = object


class SnippetsPanelViewMixin(_MixinBase):
    """Header, footer, breadcrumb, and snippet-card rendering."""

    if TYPE_CHECKING:
        _accent: str
        _all_entries: tuple[SnippetEntry, ...]
        _chip_cursor: int | None
        _chip_entries: tuple[SnippetEntry, ...]
        _chip_outbound_count: int
        _current_trigger: str | None
        _entries: tuple[SnippetEntry, ...]
        _filter_bodies: bool
        _filter_text: str
        _keymaps: SnippetPanelKeymaps
        _loading: bool
        _project_index: int
        _ring: tuple[SnippetProjectRef, ...]
        _snapshot: SnippetProjectSnapshot | None
        _trail: list[str]

        def _selected_entry(self) -> SnippetEntry | None: ...

        def _trigger_list(self) -> OptionList: ...

    def _loading_header_text(self) -> Text:
        return Text("SNIPPETS  ·  loading…", style=f"bold {self._accent}")

    def _update_header(self) -> None:
        header: RenderableType
        if self._loading:
            header = self._loading_header_text()
        else:
            project_display_name = (
                self._snapshot.project.display_name if self._snapshot else ""
            )
            header = build_panel_header(
                project_display_name=project_display_name,
                snippet_count=len(self._all_entries),
                project_index=self._project_index,
                project_count=len(self._ring),
                accent=self._accent,
                include_bodies=self._filter_bodies,
            )
        self.query_one("#snippets-panel-header", Static).update(header)

    def _resize_trigger_rail(self) -> None:
        """Fit the trigger rail to its widest row within the panel's width."""
        try:
            body = self.query_one("#snippets-panel-body", Horizontal)
            trigger_list = self._trigger_list()
        except NoMatches:
            return
        width = trigger_rail_width(self._all_entries, available_width=body.size.width)
        current = trigger_list.styles.width
        if current is not None and current.is_cells and int(current.value) == width:
            return
        trigger_list.styles.width = width

    def _update_footer(self) -> None:
        entry = self._selected_entry()
        has_source_path = bool(
            entry is not None and (entry.origin.path or entry.origin.display_path)
        )
        focused_relation_trigger = None
        if self._chip_cursor is not None and 0 <= self._chip_cursor < len(
            self._chip_entries
        ):
            focused_relation_trigger = self._chip_entries[self._chip_cursor].trigger
        footer = build_panel_footer(
            self._keymaps,
            has_entries=bool(self._entries),
            has_source_path=has_source_path,
            ring_size=len(self._ring),
            has_relations=bool(self._chip_entries),
            has_trail=bool(self._trail),
            focused_relation_trigger=focused_relation_trigger,
        )
        footer_widget = self.query_one("#snippets-panel-footer", Static)
        footer_widget.update(footer)
        footer_widget.display = bool(footer)

    def _trail_strip(self) -> Static:
        return self.query_one("#snippets-panel-trail", Static)

    def _update_trail_strip(self) -> None:
        trail_widget = self._trail_strip()
        if not self._trail or self._current_trigger is None:
            trail_widget.display = False
            trail_widget.update("")
            return
        trail_widget.display = True
        trail_widget.update(
            build_trail_strip(
                (*self._trail, self._current_trigger), accent=self._accent
            )
        )

    def _render_snippet_card(self) -> None:
        self._update_trail_strip()
        title_widget = self.query_one("#snippets-panel-card-title", Static)
        raw_widget = self.query_one("#snippets-panel-card-raw", Static)
        composed_widget = self.query_one("#snippets-panel-card-composed", Static)
        meta_widget = self.query_one("#snippets-panel-card-meta", Static)

        if self._loading:
            title_widget.update("")
            raw_widget.update("Loading…")
            composed_widget.update("")
            meta_widget.update("")
            return

        snapshot = self._snapshot
        if snapshot is None or not self._ring:
            title_widget.update("")
            raw_widget.update("No projects are available.")
            composed_widget.update("")
            meta_widget.update("")
            return

        if snapshot.catalog is None:
            title_widget.update("")
            raw_widget.update("")
            composed_widget.update("")
            if snapshot.diagnostics:
                meta_widget.update(
                    build_diagnostics_message(snapshot.diagnostics, accent=self._accent)
                )
            else:
                meta_widget.update(
                    build_empty_project_message(
                        snapshot.project.display_name, accent=self._accent
                    )
                )
            return

        entry = self._selected_entry()
        if entry is None:
            title_widget.update("")
            raw_widget.update("")
            composed_widget.update("")
            if self._filter_text:
                meta_widget.update(build_no_match_message(self._filter_text))
            elif snapshot.diagnostics:
                meta_widget.update(
                    build_diagnostics_message(snapshot.diagnostics, accent=self._accent)
                )
            else:
                meta_widget.update(
                    build_empty_project_message(
                        snapshot.project.display_name, accent=self._accent
                    )
                )
            return

        project_name = snapshot.project.display_name
        title_widget.update(
            build_snippet_card_title(
                entry, project_name=project_name, accent=self._accent
            )
        )
        raw_widget.update(build_raw_section(entry, accent=self._accent))
        composed_widget.update(build_composed_section(entry, accent=self._accent))
        outbound = self._chip_entries[: self._chip_outbound_count]
        inbound = self._chip_entries[self._chip_outbound_count :]
        focused_relation_number = (
            self._chip_cursor + 1 if self._chip_cursor is not None else None
        )
        meta_widget.update(
            build_snippet_card_meta(
                entry,
                project_name=project_name,
                accent=self._accent,
                outbound=outbound,
                inbound=inbound,
                focused_relation_number=focused_relation_number,
                layer_diagnostics=snapshot.diagnostics,
            )
        )


__all__ = ["SnippetsPanelViewMixin"]

"""Widget updates for the Glossary panel's header, footer, trail, and card.

Everything here writes already-built renderables from
:mod:`sase.ace.tui.modals.glossary_panel_rendering` into the panel's mounted
widgets; the pure text builders themselves live in that module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import RenderableType
from rich.text import Text
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Markdown, Static

from .glossary_panel_rendering import (
    build_definition_card_meta,
    build_definition_card_title,
    build_diagnostics_message,
    build_empty_project_message,
    build_no_match_message,
    build_panel_footer,
    build_panel_header,
    build_trail_strip,
    term_rail_width,
)
from .glossary_preview_render import glossary_definition_markdown, glossary_source_path

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
    from textual.widgets import OptionList

    from sase.ace.tui.glossary_panel_catalog import (
        GlossaryProjectRef,
        GlossaryProjectSnapshot,
    )
    from sase.ace.tui.keymaps import GlossaryPanelKeymaps
    from sase.core.glossary_facade import GlossaryEntry
else:
    _MixinBase = object


class GlossaryPanelViewMixin(_MixinBase):
    """Header, footer, breadcrumb, and definition-card rendering."""

    if TYPE_CHECKING:
        _accent: str
        _all_entries: tuple[GlossaryEntry, ...]
        _chip_cursor: int | None
        _chip_entries: tuple[GlossaryEntry, ...]
        _chip_outbound_count: int
        _current_term: str | None
        _entries: tuple[GlossaryEntry, ...]
        _filter_text: str
        _keymaps: GlossaryPanelKeymaps
        _loading: bool
        _project_index: int
        _ring: tuple[GlossaryProjectRef, ...]
        _snapshot: GlossaryProjectSnapshot | None
        _trail: list[str]

        def _selected_entry(self) -> GlossaryEntry | None: ...

        def _term_list(self) -> OptionList: ...

    def _loading_header_text(self) -> Text:
        return Text("GLOSSARY  ·  loading…", style=f"bold {self._accent}")

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
                term_count=len(self._all_entries),
                project_index=self._project_index,
                project_count=len(self._ring),
                accent=self._accent,
            )
        self.query_one("#glossary-panel-header", Static).update(header)

    def _resize_term_rail(self) -> None:
        """Fit the term rail to its widest row within the panel's width."""
        try:
            body = self.query_one("#glossary-panel-body", Horizontal)
            term_list = self._term_list()
        except NoMatches:
            return
        width = term_rail_width(self._all_entries, available_width=body.size.width)
        current = term_list.styles.width
        if current is not None and current.is_cells and int(current.value) == width:
            return
        term_list.styles.width = width

    def _update_footer(self) -> None:
        entry = self._selected_entry()
        has_source_path = (
            entry is not None
            and self._snapshot is not None
            and self._snapshot.catalog is not None
            and glossary_source_path(self._snapshot.catalog, entry) is not None
        )
        focused_relation_term = None
        if self._chip_cursor is not None and 0 <= self._chip_cursor < len(
            self._chip_entries
        ):
            focused_relation_term = self._chip_entries[self._chip_cursor].term
        footer = build_panel_footer(
            self._keymaps,
            has_entries=bool(self._entries),
            has_source_path=has_source_path,
            ring_size=len(self._ring),
            has_relations=bool(self._chip_entries),
            has_trail=bool(self._trail),
            focused_relation_term=focused_relation_term,
        )
        footer_widget = self.query_one("#glossary-panel-footer", Static)
        footer_widget.update(footer)
        footer_widget.display = bool(footer)

    def _trail_strip(self) -> Static:
        return self.query_one("#glossary-panel-trail", Static)

    def _update_trail_strip(self) -> None:
        trail_widget = self._trail_strip()
        if not self._trail or self._current_term is None:
            trail_widget.display = False
            trail_widget.update("")
            return
        trail_widget.display = True
        trail_widget.update(
            build_trail_strip((*self._trail, self._current_term), accent=self._accent)
        )

    def _render_definition_card(self) -> None:
        self._update_trail_strip()
        title_widget = self.query_one("#glossary-panel-card-title", Static)
        definition_widget = self.query_one("#glossary-panel-card-definition", Markdown)
        meta_widget = self.query_one("#glossary-panel-card-meta", Static)

        if self._loading:
            title_widget.update("")
            definition_widget.update("Loading…")
            meta_widget.update("")
            return

        snapshot = self._snapshot
        if snapshot is None or not self._ring:
            title_widget.update("")
            definition_widget.update("No projects are available.")
            meta_widget.update("")
            return

        if snapshot.catalog is None:
            title_widget.update("")
            definition_widget.update("")
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
            definition_widget.update("")
            if self._filter_text:
                meta_widget.update(build_no_match_message(self._filter_text))
            else:
                meta_widget.update("")
            return

        project_name = snapshot.project.display_name
        title_widget.update(
            build_definition_card_title(
                entry, project_name=project_name, accent=self._accent
            )
        )
        definition_widget.update(glossary_definition_markdown(snapshot.catalog, entry))
        outbound = self._chip_entries[: self._chip_outbound_count]
        inbound = self._chip_entries[self._chip_outbound_count :]
        focused_relation_number = (
            self._chip_cursor + 1 if self._chip_cursor is not None else None
        )
        meta_widget.update(
            build_definition_card_meta(
                snapshot.catalog,
                entry,
                project_name=project_name,
                accent=self._accent,
                outbound=outbound,
                inbound=inbound,
                focused_relation_number=focused_relation_number,
            )
        )


__all__ = ["GlossaryPanelViewMixin"]

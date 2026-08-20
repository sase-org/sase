"""Term, filter, and project navigation for the Glossary panel.

The three movement axes the term list itself owns: cursor motion plus
definition scrolling, the inline filter box, and `p`/`P` project cycling with
its refresh. Relation-chip travel is the fourth axis and lives in
:mod:`sase.ace.tui.modals.glossary_panel_travel`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import VerticalScroll
from textual.widgets import Input

from sase.ace.tui.glossary_panel_catalog import invalidate_glossary_project

from .glossary_panel_state import _FILTER_INPUT_ID

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
    from textual.widgets import OptionList

    from sase.ace.tui.glossary_panel_catalog import (
        GlossaryProjectRef,
        GlossaryProjectSnapshot,
    )
    from sase.core.glossary_facade import GlossaryEntry
else:
    _MixinBase = object


class GlossaryPanelNavigationMixin(_MixinBase):
    """Term cursor, definition scrolling, filtering, and project cycling."""

    if TYPE_CHECKING:
        _current_term: str | None
        _entries: tuple[GlossaryEntry, ...]
        _filter_definitions: bool
        _filter_text: str
        _host_visible: bool
        _loading: bool
        _project_index: int
        _project_selection_memory: dict[str, str]
        _ring: tuple[GlossaryProjectRef, ...]
        _snapshot: GlossaryProjectSnapshot | None
        _trail: list[str]

        def _apply_filter(
            self,
            pattern: str,
            *,
            definitions: bool,
            preferred_term: str | None = None,
        ) -> None: ...

        def _filter_input(self) -> Input: ...

        def _start_project_load(self) -> None: ...

        def _term_list(self) -> OptionList: ...

    # --- term navigation ----------------------------------------------

    def action_next_term(self) -> None:
        if self._entries:
            self._term_list().action_cursor_down()

    def action_prev_term(self) -> None:
        if self._entries:
            self._term_list().action_cursor_up()

    def action_first_term(self) -> None:
        if self._entries:
            self._term_list().highlighted = 0

    def action_last_term(self) -> None:
        if self._entries:
            self._term_list().highlighted = len(self._entries) - 1

    def action_scroll_definition_down(self) -> None:
        scroll = self.query_one("#glossary-panel-detail", VerticalScroll)
        scroll.scroll_relative(
            y=max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_scroll_definition_up(self) -> None:
        scroll = self.query_one("#glossary-panel-detail", VerticalScroll)
        scroll.scroll_relative(
            y=-max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    # --- filter -------------------------------------------------------

    def action_filter_terms(self) -> None:
        filter_input = self._filter_input()
        filter_input.display = True
        filter_input.value = self._filter_text
        filter_input.focus()

    def action_toggle_definition_filter(self) -> None:
        self._apply_filter(self._filter_text, definitions=not self._filter_definitions)

    def _close_filter(self) -> None:
        filter_input = self._filter_input()
        filter_input.display = False
        if self._host_visible:
            self.app.set_focus(self._term_list())

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != _FILTER_INPUT_ID:
            return
        self._apply_filter(event.value, definitions=self._filter_definitions)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != _FILTER_INPUT_ID:
            return
        self._close_filter()

    # --- project cycling ------------------------------------------------

    def action_next_project(self) -> None:
        self._cycle_project(1)

    def action_prev_project(self) -> None:
        self._cycle_project(-1)

    def _cycle_project(self, delta: int) -> None:
        if self._loading or len(self._ring) <= 1:
            return
        if self._snapshot is not None:
            self._project_selection_memory[self._snapshot.project.key] = (
                self._current_term or ""
            )
        self._project_index = (self._project_index + delta) % len(self._ring)
        self._filter_input().value = ""
        self._filter_input().display = False
        self._trail = []
        self._start_project_load()

    def action_refresh(self) -> None:
        if self._loading or not self._ring:
            return
        invalidate_glossary_project(self._ring[self._project_index].key)
        self._start_project_load()


__all__ = ["GlossaryPanelNavigationMixin"]

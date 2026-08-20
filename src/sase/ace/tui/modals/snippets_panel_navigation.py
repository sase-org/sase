"""Trigger, filter, and project navigation for the Snippets panel.

The three movement axes the trigger list itself owns: cursor motion plus
template scrolling, the inline filter box, and ``p``/``P`` project cycling
with its refresh. Relation-chip travel is the fourth axis and lives in
:mod:`sase.ace.tui.modals.snippets_panel_travel`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import VerticalScroll
from textual.widgets import Input

from sase.ace.tui.snippets_panel_catalog import invalidate_snippet_project

from .snippets_panel_state import _FILTER_INPUT_ID

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
    from textual.widgets import OptionList

    from sase.ace.tui.snippets_panel_catalog import (
        SnippetProjectRef,
        SnippetProjectSnapshot,
    )
    from sase.snippet.models import SnippetEntry
else:
    _MixinBase = object


class SnippetsPanelNavigationMixin(_MixinBase):
    """Trigger cursor, template scrolling, filtering, and project cycling."""

    if TYPE_CHECKING:
        _current_trigger: str | None
        _entries: tuple[SnippetEntry, ...]
        _filter_bodies: bool
        _filter_text: str
        _loading: bool
        _project_index: int
        _project_selection_memory: dict[str, str]
        _ring: tuple[SnippetProjectRef, ...]
        _snapshot: SnippetProjectSnapshot | None
        _trail: list[str]

        def _apply_filter(
            self,
            pattern: str,
            *,
            bodies: bool,
            preferred_trigger: str | None = None,
        ) -> None: ...

        def _filter_input(self) -> Input: ...

        def _start_project_load(self) -> None: ...

        def _trigger_list(self) -> OptionList: ...

    def action_next_snippet(self) -> None:
        if self._entries:
            self._trigger_list().action_cursor_down()

    def action_prev_snippet(self) -> None:
        if self._entries:
            self._trigger_list().action_cursor_up()

    def action_first_snippet(self) -> None:
        if self._entries:
            self._trigger_list().highlighted = 0

    def action_last_snippet(self) -> None:
        if self._entries:
            self._trigger_list().highlighted = len(self._entries) - 1

    def action_scroll_template_down(self) -> None:
        scroll = self.query_one("#snippets-panel-detail", VerticalScroll)
        scroll.scroll_relative(
            y=max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_scroll_template_up(self) -> None:
        scroll = self.query_one("#snippets-panel-detail", VerticalScroll)
        scroll.scroll_relative(
            y=-max(1, scroll.scrollable_content_region.height // 2), animate=False
        )

    def action_filter_snippets(self) -> None:
        filter_input = self._filter_input()
        filter_input.display = True
        filter_input.value = self._filter_text
        filter_input.focus()

    def action_toggle_body_filter(self) -> None:
        self._apply_filter(self._filter_text, bodies=not self._filter_bodies)

    def _close_filter(self) -> None:
        filter_input = self._filter_input()
        filter_input.display = False
        self._trigger_list().focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != _FILTER_INPUT_ID:
            return
        self._apply_filter(event.value, bodies=self._filter_bodies)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != _FILTER_INPUT_ID:
            return
        self._close_filter()

    def action_next_project(self) -> None:
        self._cycle_project(1)

    def action_prev_project(self) -> None:
        self._cycle_project(-1)

    def _cycle_project(self, delta: int) -> None:
        if self._loading or len(self._ring) <= 1:
            return
        if self._snapshot is not None and self._current_trigger:
            self._project_selection_memory[self._snapshot.project.key] = (
                self._current_trigger
            )
        self._project_index = (self._project_index + delta) % len(self._ring)
        self._filter_input().value = ""
        self._filter_input().display = False
        self._trail = []
        self._start_project_load()

    def action_refresh(self) -> None:
        if self._loading or not self._ring:
            return
        invalidate_snippet_project(self._ring[self._project_index].key)
        self._start_project_load()


__all__ = ["SnippetsPanelNavigationMixin"]

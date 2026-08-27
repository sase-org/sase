"""Back/forward trail state for ``PagerScreen``."""

from __future__ import annotations

from typing import Any

from textual.widgets import Static

from sase.ace.tui.modals.trail_strip import TrailStripEntry, build_trail_strip
from sase.ace.tui.widgets.vim_search_controller import VimSearchController
from sase.pager._chrome import section_accent
from sase.pager._labels import LabelWindowScope, PagerLabel, PagerLabelLayer
from sase.pager._layout import ComposedBody
from sase.pager.app import PagerExit, PendingAction
from sase.pager.document import PagerSection
from sase.pager.trail import PagerSearchState, PagerTrailEntry, append_bounded_trail


class PagerTrailMixin:
    """Own pager-owned back/forward history and search-state snapshots."""

    _body: ComposedBody | None
    _body_width: int | None
    _footer_status: str | None
    _label_layer: PagerLabelLayer | None
    _label_pending_prefix: str
    _label_window_scope: LabelWindowScope | None
    _last_activated_label: PagerLabel | None
    _pending_action: PendingAction

    def action_trail_back(self: Any) -> None:
        if not self._back_trail:
            self.dismiss(PagerExit(trail_exhausted=True))
            return
        self._resolve_generation += 1
        target = self._back_trail.pop()
        append_bounded_trail(self._forward_trail, self._current_view_state())
        self._restore_view_state(target)

    def action_trail_forward(self: Any) -> None:
        if not self._forward_trail:
            return
        self._resolve_generation += 1
        target = self._forward_trail.pop()
        append_bounded_trail(self._back_trail, self._current_view_state())
        self._restore_view_state(target)

    def _push_trail_entry(self: Any) -> None:
        append_bounded_trail(self._back_trail, self._current_view_state())

    def _restore_view_state(self: Any, state: PagerTrailEntry) -> None:
        self.document = state.document
        self._body = None
        self._body_width = None
        self._label_layer = None
        self._label_pending_prefix = ""
        self._label_window_scope = state.label_anchor
        self._last_activated_label = None
        self._pending_action = "follow"
        self._footer_status = None
        self._ensure_body()
        self._restore_search_state(state.search)
        self._update_trail()
        self._update_footer()
        self._update_subject()
        self.call_after_refresh(
            lambda: self._restore_trail_scroll(
                x=state.scroll_x,
                y=state.scroll_y,
            )
        )

    def _restore_trail_scroll(self: Any, *, x: int, y: int) -> None:
        self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)
        self._update_subject()
        self._update_trail()

    def _current_view_state(self: Any) -> PagerTrailEntry:
        section = self._current_section_or_none()
        scroll = self._body_scroll()
        return PagerTrailEntry(
            document=self.document,
            document_identity=self._document_identity(),
            document_title=self.document.title,
            section_identity=section.identity if section is not None else "",
            section_title=section.title if section is not None else self.document.title,
            section_kind=section.kind if section is not None else "",
            scroll_x=int(scroll.scroll_x),
            scroll_y=int(scroll.scroll_y),
            search=self._current_search_state(),
            label_anchor=self._label_window_scope,
        )

    def _current_search_state(self: Any) -> PagerSearchState:
        return PagerSearchState(
            mode=self._search.mode,
            direction=self._search.direction,
            query=self._search.query,
            corpus=self._search.corpus,
            line_starts=tuple(self._search.line_starts),
            match_spans=tuple(self._search.match_spans),
            current_selection=self._search.current_selection,
            origin_offset=self._search.origin_offset,
            restore_scroll_x=self._search.restore_scroll_x,
            restore_scroll_y=self._search.restore_scroll_y,
            last_search=self._search.last_search,
        )

    def _reset_search_state(self: Any) -> None:
        if self._search.is_active:
            self._search.exit(restore_scroll=False, refresh=False)
        self._search = VimSearchController(self)
        self.vim_search_hide_overlay()

    def _restore_search_state(self: Any, state: PagerSearchState) -> None:
        if self._search.is_active:
            self._search.exit(restore_scroll=False, refresh=False)
        self._search.mode = state.mode
        self._search.direction = state.direction
        self._search.query = state.query
        self._search.corpus = state.corpus
        self._search.line_starts = state.line_starts
        self._search.match_spans = state.match_spans
        self._search.current_selection = state.current_selection
        self._search.origin_offset = state.origin_offset
        self._search.restore_scroll_x = state.restore_scroll_x
        self._search.restore_scroll_y = state.restore_scroll_y
        self._search.last_search = state.last_search
        if state.mode == "off":
            self.vim_search_hide_overlay()
            return
        self.vim_search_show_overlay()
        self._search._render_overlay()
        self._search._render_command_line()
        self.vim_search_focus_overlay()

    def _document_identity(self: Any) -> str:
        if len(self.document.sections) == 1:
            return self.document.sections[0].identity
        if self.document.sections:
            return "|".join(section.identity for section in self.document.sections)
        return self.document.title

    def _current_section_or_none(self: Any) -> PagerSection | None:
        if not self.document.sections:
            return None
        return self._current_section()

    def _trail_strip_entries(self: Any) -> tuple[TrailStripEntry, ...]:
        if not self._back_trail:
            return ()
        entries = [
            TrailStripEntry(entry.section_title, kind=entry.section_kind)
            for entry in self._back_trail
        ]
        current = self._current_section_or_none()
        if current is None:
            entries.append(TrailStripEntry(self.document.title))
        else:
            entries.append(TrailStripEntry(current.title, kind=current.kind))
        return tuple(entries)

    def _update_trail(self: Any) -> None:
        trail = self.query_one("#pager-trail", Static)
        entries = self._trail_strip_entries()
        if not entries:
            trail.update("")
            trail.add_class("hidden")
            return
        width = max(int(trail.size.width) - 2, 1)
        current = self._current_section_or_none()
        accent = "#AFAFAF" if current is None else section_accent(current.kind)
        trail.update(build_trail_strip(entries, accent=accent, max_width=width))
        trail.remove_class("hidden")


__all__ = ["PagerTrailMixin"]

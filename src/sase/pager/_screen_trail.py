"""Back/forward trail state for ``PagerScreen``."""

from __future__ import annotations

from typing import Any

from textual.widgets import Static

from sase.ace.tui.widgets.vim_search_controller import (
    VimSearchController,
    line_start_offsets,
)
from sase.pager._labels import LabelWindowScope, PagerLabel, PagerLabelLayer
from sase.pager._layout import (
    ComposedBody,
    reading_anchor_at_row,
    row_for_reading_anchor,
)
from sase.pager._trail_chrome import (
    PagerTrailSnapshot,
    build_pager_trail_snapshot,
    render_trail_band,
)
from sase.pager.app import ViewPendingAction
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
    _pending_action: ViewPendingAction
    _trail_render_signature: object | None

    def action_trail_back(self: Any) -> None:
        if not self._back_trail:
            self.pager_host.close_view(self, trail_exhausted=True)
            return
        self._resolve_generation += 1
        history_bump = getattr(self, "_bump_history_generation", None)
        if callable(history_bump):
            history_bump()
        target = self._back_trail.pop()
        append_bounded_trail(self._forward_trail, self._current_view_state())
        self._restore_view_state(target)

    def action_trail_forward(self: Any) -> None:
        if not self._forward_trail:
            return
        self._resolve_generation += 1
        history_bump = getattr(self, "_bump_history_generation", None)
        if callable(history_bump):
            history_bump()
        target = self._forward_trail.pop()
        append_bounded_trail(self._back_trail, self._current_view_state())
        self._restore_view_state(target)

    def _push_trail_entry(self: Any) -> None:
        append_bounded_trail(self._back_trail, self._current_view_state())

    def _restore_view_state(self: Any, state: PagerTrailEntry) -> None:
        self.document = state.document
        rehydrate = getattr(self, "_rehydrate_history_pins", None)
        if callable(rehydrate):
            rehydrate(state.version_pins)
        self._body = None
        self._body_width = None
        self._label_layer = None
        self._label_pending_prefix = ""
        self._label_window_scope = state.label_anchor
        self._last_activated_label = None
        self._pending_action = "follow"
        self._footer_status = None
        self._clear_goto_state()
        self._goto_mark = state.line_mark
        self._reset_syntax_for_new_document()
        self._ensure_body()
        self._restore_search_state(state.search)
        self._update_trail()
        self._update_footer()
        self._update_subject()
        self._start_syntax_preparation_after_paint()
        try:
            start_history = getattr(self, "_start_history_discovery_after_paint", None)
            if callable(start_history):
                start_history()
        except Exception:
            pass
        target_y = state.scroll_y
        if state.reading_anchor is not None and self._body is not None:
            try:
                target_y = row_for_reading_anchor(self._body, state.reading_anchor)
            except Exception:
                target_y = state.scroll_y
        scroll_x = state.scroll_x
        self.call_after_refresh(
            lambda: self._restore_trail_scroll(
                x=scroll_x,
                y=target_y,
            )
        )

    def _restore_trail_scroll(self: Any, *, x: int, y: int) -> None:
        try:
            if not self.is_mounted:
                return
        except Exception:
            pass
        try:
            self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)
            self._update_subject()
            self._update_trail()
        except Exception:
            pass

    def _current_view_state(self: Any) -> PagerTrailEntry:
        section = self._current_section_or_none()
        scroll = self._body_scroll()
        states = getattr(self, "_history_states", None) or {}
        trail_pins: list[tuple[str, object]] = []
        for item in self.document.sections:
            pin = None
            try:
                state = states.get(item.identity)
                pin = getattr(state, "current_pin", None) if state is not None else None
            except Exception:
                pin = None
            if pin is None:
                pin = item.version_pin
            trail_pins.append((item.identity, pin))
        pins: tuple[tuple[str, object], ...] = tuple(trail_pins)
        scroll_y = int(scroll.scroll_y)
        anchor = None
        body = getattr(self, "_body", None)
        if body is not None:
            try:
                anchor = reading_anchor_at_row(body, scroll_y)
            except Exception:
                anchor = None
        return PagerTrailEntry(
            document=self.document,
            document_identity=self._document_identity(),
            document_title=self.document.title,
            section_identity=section.identity if section is not None else "",
            section_title=section.title if section is not None else self.document.title,
            section_kind=section.kind if section is not None else "",
            scroll_x=int(scroll.scroll_x),
            scroll_y=scroll_y,
            search=self._current_search_state(),
            label_anchor=self._label_window_scope,
            line_mark=self._goto_mark,
            version_pins=pins,
            reading_anchor=anchor,
        )

    def _current_search_state(self: Any) -> PagerSearchState:
        # No corpus or line starts: both rebuild from the entry's document
        # on restore, so trail entries never pin search copies.
        return PagerSearchState(
            mode=self._search.mode,
            direction=self._search.direction,
            query=self._search.query,
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
        if state.mode == "off":
            self._search.corpus = ""
            self._search.line_starts = (0,)
        else:
            # The corpus is a pure function of the restored document (set
            # by the caller before this runs), so rebuilding it yields
            # exactly the text the stored match offsets were computed
            # against.
            rebuilt = self.vim_search_corpus()
            self._search.corpus = rebuilt
            self._search.line_starts = line_start_offsets(rebuilt)
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

    def _trail_snapshot(self: Any) -> PagerTrailSnapshot:
        version_pins, current_suffix = self._trail_version_info()
        return build_pager_trail_snapshot(
            back=self._back_trail,
            document=self.document,
            document_identity=self._document_identity(),
            current_section=self._current_section_or_none(),
            current_line_mark=self._goto_mark,
            forward=self._forward_trail,
            version_pins=version_pins,
            current_suffix=current_suffix,
        )

    def _trail_version_info(self: Any) -> tuple[dict[str, object], str]:
        """Return version pins by identity plus the live moment's suffix.

        Pins come from each section's history state (falling back to the
        section's own pin); the current suffix comes from the live
        moment, which also names tombstones. Fails open to no suffixes.
        """
        pins: dict[str, object] = {}
        suffix = ""
        try:
            from sase.pager._trail_chrome import suffix_for_moment
            from sase.pager.history.moment import moment_for_state

            states = getattr(self, "_history_states", None) or {}
            current = self._current_section_or_none()
            for section in self.document.sections:
                state = states.get(section.identity)
                pin = None
                if state is not None:
                    pin = getattr(state, "current_pin", None)
                if pin is None:
                    pin = getattr(section, "version_pin", None)
                if pin is not None:
                    pins[section.identity] = pin
                if current is not None and section.identity == current.identity:
                    suffix = suffix_for_moment(
                        moment_for_state(state) if state is not None else None
                    )
        except Exception:
            return ({}, "")
        return (pins, suffix)

    def _update_trail(self: Any) -> None:
        from sase.pager._time_band import chrome_row_budget

        trail = self.query_one("#pager-trail", Static)
        rule = self.query_one("#pager-chrome-rule", Static)
        framed = bool(getattr(self, "_pane_framed", False))
        snapshot = self._trail_snapshot()
        if not snapshot.visible:
            signature: object = (snapshot.signature, "hidden")
            if self._trail_render_signature == signature:
                return
            self._trail_render_signature = signature
            trail.update("")
            trail.add_class("hidden")
            trail.remove_class("compact")
            if not framed:
                rule.remove_class("hidden")
            return

        width = self._trail_paint_width()
        screen_height = max(int(self._chrome_height()), 1)
        time_mode = "hidden"
        time_mode_fn = getattr(self, "_time_band_mode", None)
        if callable(time_mode_fn):
            try:
                time_mode = str(time_mode_fn() or "hidden")
            except Exception:
                time_mode = "hidden"
        rows, _ = chrome_row_budget(screen_height, snapshot.visible, time_mode)
        signature = (snapshot.signature, width, rows)
        if self._trail_render_signature == signature:
            return
        self._trail_render_signature = signature
        styles_fn = getattr(self, "_history_styles", None)
        version_style = None
        if callable(styles_fn):
            try:
                version_style = styles_fn().past
            except Exception:
                version_style = None
        trail.update(
            render_trail_band(
                snapshot,
                width=width,
                screen_height=screen_height,
                version_style=version_style,
            )
        )
        trail.remove_class("hidden")
        if rows == 1:
            trail.add_class("compact")
        else:
            trail.remove_class("compact")
        rule.add_class("hidden")

    def _trail_paint_width(self: Any) -> int:
        trail = self.query_one("#pager-trail", Static)
        padding = trail.styles.padding
        horizontal = int(padding.left) + int(padding.right)
        width = int(trail.size.width)
        if width <= 0:
            width = max(int(self.size.width), int(self._body_scroll().size.width))
        return max(width - horizontal, 0)


__all__ = ["PagerTrailMixin"]

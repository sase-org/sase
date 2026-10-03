"""Body layout, paint, scrolling, and section-position helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.text import Text
from textual.geometry import Size

from sase.pager._body_layout import BodyLayout, build_body_layout
from sase.pager._body_lines import logical_line_end, logical_line_starts
from sase.pager._body_rows import BodyPaintState, BodyRenderer
from sase.pager._gutter import gutter_width, logical_line_count
from sase.pager._labels import (
    LabelWindowScope,
    PAGER_LABEL_TWO_KEY_CAPACITY,
    PagerLabel,
    PagerLabelLayer,
    build_label_layer,
)
from sase.pager._layout import (
    current_section_index,
    reading_anchor_at_row,
    row_for_reading_anchor,
)
from sase.pager._screen_widgets import PagerBodyScroll
from sase.pager.app import ViewPendingAction
from sase.pager.document import PagerDocument, PagerSection


class PagerBodyMixin:
    """Own the virtual body layout, its paint epoch, and scroll commands."""

    _body: BodyLayout | None
    _body_renderer: BodyRenderer | None
    _body_paint_epoch: int
    _label_layer: PagerLabelLayer | None
    _label_window_scope: LabelWindowScope | None
    _label_pending_prefix: str
    _last_activated_label: PagerLabel | None
    _pending_action: ViewPendingAction
    _refresh_document_fn: Callable[[], PagerDocument | None] | None
    _refresh_in_flight: bool

    def action_scroll_down(self: Any) -> None:
        self._body_scroll().scroll_relative(y=1, animate=False)
        self._after_scroll()

    def action_scroll_up(self: Any) -> None:
        self._body_scroll().scroll_relative(y=-1, animate=False)
        self._after_scroll()

    def action_scroll_half_down(self: Any) -> None:
        scroll = self._body_scroll()
        scroll.scroll_relative(y=max(1, scroll.size.height // 2), animate=False)
        self._after_scroll()

    def action_scroll_half_up(self: Any) -> None:
        scroll = self._body_scroll()
        scroll.scroll_relative(y=-max(1, scroll.size.height // 2), animate=False)
        self._after_scroll()

    def action_scroll_top(self: Any) -> None:
        self._body_scroll().scroll_to(y=0, animate=False, immediate=True)
        self._after_scroll()

    def action_scroll_bottom(self: Any) -> None:
        scroll = self._body_scroll()
        scroll.scroll_to(y=scroll.max_scroll_y, animate=False, immediate=True)
        self._after_scroll()

    def action_next_section(self: Any) -> None:
        """Scroll so the next section's rule sits at row 0 (design doc D5).

        This is a scroll, not a screen swap, because the pager is one
        continuous document rather than independently-loaded panels.
        """
        self._goto_section(1)

    def action_prev_section(self: Any) -> None:
        self._goto_section(-1)

    def action_refresh(self: Any) -> None:
        refresh_document_fn = self._refresh_document_fn
        if refresh_document_fn is None:
            self._dangling_refs.clear()
            self._resolve_generation += 1
            self._clear_goto_state()
            self._invalidate_body_layout(relabel=True)
            self._after_scroll()
            return
        if self._refresh_in_flight:
            return
        self._refresh_in_flight = True

        def do_refresh() -> None:
            try:
                try:
                    document = refresh_document_fn()
                except Exception:
                    document = None
                self.app.call_from_thread(self._apply_refreshed_document, document)
            finally:
                self._refresh_in_flight = False

        self.run_worker(do_refresh, thread=True)

    def _apply_refreshed_document(self: Any, document: PagerDocument | None) -> None:
        """Swap in a freshly re-snapshotted document, or keep the current one.

        Called on the UI thread from :meth:`action_refresh`'s worker. A
        ``None`` document means the provider found nothing to refresh (the
        row disappeared) or raised; the current document is kept either way,
        with a brief footer status standing in for the usual full recompose.
        """
        try:
            if not self.is_mounted:
                return
        except Exception:
            pass
        if document is None:
            self._set_footer_status("Refresh failed — keeping current document")
            return

        previous_identity = None
        if self.document.sections:
            previous_identity = self.document.sections[
                self._current_section_index()
            ].identity

        self.document = document
        self._dangling_refs.clear()
        self._resolve_generation += 1
        self._clear_goto_state()
        self._search.exit(restore_scroll=False, refresh=False)
        self._label_pending_prefix = ""
        self._pending_action = "follow"
        self._last_activated_label = None
        self._body = None
        self._label_layer = None
        self._invalidate_body_layout()

        target_row = 0
        body = self._body
        if previous_identity is not None and body is not None:
            for index, section in enumerate(self.document.sections):
                if section.identity == previous_identity:
                    target_row = body.section_offsets[index]
                    break
        scroll = self._body_scroll()
        clamped = max(0, min(target_row, scroll.max_scroll_y))
        scroll.scroll_to(y=clamped, animate=False, immediate=True)
        self._set_footer_status(None)
        self._after_scroll()

    def _goto_section(self: Any, direction: int) -> None:
        if self._body is None or len(self.document.sections) <= 1:
            return
        scroll = self._body_scroll()
        offsets = self._body.section_offsets
        index = current_section_index(offsets, int(scroll.scroll_y))
        target = index + direction
        if target >= len(offsets):
            scroll.scroll_to(y=scroll.max_scroll_y, animate=False, immediate=True)
        else:
            target_row = offsets[max(target, 0)]
            scroll.scroll_to(y=target_row, animate=False, immediate=True)
        self._after_scroll()

    def _after_scroll(self: Any) -> None:
        self._refresh_window_scoped_labels_if_needed()
        self._schedule_syntax_preparation()
        self.call_after_refresh(self._update_chrome_position)

    def _update_chrome_position(self: Any) -> None:
        self._update_subject()
        self._update_trail()

    def _body_scroll(self: Any) -> PagerBodyScroll:
        return self.query_one("#pager-body-scroll", PagerBodyScroll)

    def row_text(self: Any, row: int) -> Text:
        """Return the row ``Text`` for absolute *row*.

        The match-painted line while lazy search is active, the legacy
        overlay line while a full-text overlay is painted, else the model
        row from the current paint epoch.
        """
        try:
            widget = self._body_scroll()
        except Exception:
            widget = None
        if widget is not None:
            try:
                if widget.match_active:
                    return self._search_row_text(row)
            except Exception:
                pass
            if widget.overlay_active:
                return widget.overlay_line(row)
        renderer = self._body_renderer
        if renderer is None:
            return Text("")
        return renderer.render_row(row)

    def row_plain_text(self: Any, row: int) -> str:
        """Return the unstyled logical-line plain text for absolute *row*.

        Bypasses the styled renderer, so a failing paint epoch still shows
        the line itself.
        """
        try:
            widget = self._body_scroll()
        except Exception:
            widget = None
        if widget is not None:
            try:
                if widget.match_active:
                    try:
                        return self._search_row_text(row).plain
                    except Exception:
                        return ""
            except Exception:
                pass
            if widget.overlay_active:
                try:
                    return widget.overlay_line(row).plain
                except Exception:
                    return ""
        return self._model_plain_row(row)

    def _model_plain_row(self: Any, row: int) -> str:
        body = self._body
        if body is None:
            return ""
        try:
            location = body.locate(row)
        except Exception:
            return ""
        states = body.section_states
        if location.section_index >= len(states):
            return ""
        state = states[location.section_index]
        if location.kind == "rule":
            rule = state.rule
            return rule.plain if rule is not None else ""
        if location.kind == "custom":
            if not state.prerendered:
                return ""
            slot = max(0, min(location.wrap_index, len(state.prerendered) - 1))
            return state.prerendered[slot].plain
        if location.kind != "line":
            return ""
        sections = body.bound_sections
        if location.section_index >= len(sections):
            return ""
        plain = sections[location.section_index].plain_text
        starts = logical_line_starts(plain)
        if location.line < 1 or location.line > len(starts):
            return ""
        end = logical_line_end(starts, location.line - 1, plain)
        return plain[starts[location.line - 1] : end]

    def _current_paint_state(self: Any) -> BodyPaintState:
        """Build the paint epoch state from the current marks and styles."""
        mark = getattr(self, "_goto_mark", None)
        accent = self._goto_accent_for_mark() if mark is not None else None
        marks_fn = getattr(self, "_history_marks_for_body", None)
        change_marks = None
        if callable(marks_fn):
            try:
                change_marks, _removal_anchors = marks_fn()
            except Exception:
                change_marks = None
        styles_fn = getattr(self, "_history_styles", None)
        styles = styles_fn() if callable(styles_fn) else None
        rail_styles = self._history_rail_styles(styles)
        surface = None
        try:
            candidate = getattr(styles, "background", None)
            if isinstance(candidate, str) and candidate:
                surface = candidate
        except Exception:
            surface = None
        if surface is None:
            try:
                palette = getattr(self, "_syntax_palette", None)
                candidate = getattr(palette, "background", None)
                if isinstance(candidate, str) and candidate:
                    surface = candidate
            except Exception:
                surface = None
        return BodyPaintState(
            label_layer=self._label_layer,
            pending_prefix=self._label_pending_prefix,
            prepared_sections=self._prepared_section_texts(),
            line_mark=mark,
            goto_accent=accent,
            change_marks=change_marks,
            rail_styles=rail_styles,
            history_styles=styles,
            surface=surface,
        )

    def _invalidate_body_paint(self: Any) -> None:
        """Repaint visible rows without relaying out the document.

        Builds a new renderer on the current layout, bumps the paint
        epoch, and refreshes without layout. Scroll position and
        ``lines_laid_out`` never change here.
        """
        if self._body is None:
            self._ensure_body_layout()
            return
        self._body_renderer = BodyRenderer(self._body, self._current_paint_state())
        try:
            self._body_paint_epoch = int(self._body_paint_epoch) + 1
        except Exception:
            self._body_paint_epoch = 1
        try:
            widget = self._body_scroll()
        except Exception:
            return
        try:
            widget.clear_strip_cache()
        except Exception:
            pass
        try:
            widget.refresh()
        except Exception:
            pass

    def _invalidate_body_layout(self: Any, *, relabel: bool = False) -> None:
        """Rebuild or relabel the integer layout, then repaint the widget.

        A label-set change at the same width relabels in place and keeps
        the scroll; anything else rebuilds from the document (a real width
        change restores the reading anchor) and never scrolls otherwise.
        """
        width = self._body_paint_width()
        # At most two passes: pointing virtual_size at the fresh layout
        # can show or hide the scrollbar, which moves the paint width
        # (for example a transient scrollbar while mounting). The second
        # pass converges on the settled width instead of stranding the
        # layout one transient behind the paint.
        for _pass in range(2):
            old = self._body
            new_layer = self._build_label_layer(width)
            if relabel and old is not None and width == old.width:
                try:
                    new_body = old.relabel(new_layer)
                except Exception:
                    new_body = None
                if new_body is not None:
                    self._label_layer = new_layer
                    self._body = new_body
                    self._body_renderer = BodyRenderer(
                        new_body, self._current_paint_state()
                    )
                    self._sync_body_widget()
                    return
            anchor = None
            anchor_scroll_y = 0
            if old is not None and width != old.width:
                try:
                    anchor_scroll_y = int(self._body_scroll().scroll_y)
                except Exception:
                    anchor_scroll_y = 0
                try:
                    anchor = reading_anchor_at_row(old, anchor_scroll_y)
                except Exception:
                    anchor = None
            marks_fn = getattr(self, "_history_marks_for_body", None)
            removal_anchors = None
            if callable(marks_fn):
                try:
                    _change_marks, removal_anchors = marks_fn()
                except Exception:
                    removal_anchors = None
            self._label_layer = new_layer
            new_body = build_body_layout(
                self.document,
                width,
                label_layer=new_layer,
                prepared_sections=self._prepared_section_texts(),
                removal_anchors=removal_anchors,
            )
            self._body = new_body
            self._body_renderer = BodyRenderer(new_body, self._current_paint_state())
            if anchor is not None:
                self._restore_reading_anchor(anchor, scroll_y=anchor_scroll_y)
            self._sync_body_widget()
            try:
                settled = self._body_paint_width()
            except Exception:
                return
            if settled == width:
                return
            width = settled
            relabel = False

    def _ensure_body_layout(self: Any) -> None:
        """Build the layout only when it is missing or the width changed."""
        body = self._body
        if body is not None and self._body_renderer is not None:
            try:
                if int(self._body_paint_width()) == int(body.width):
                    return
            except Exception:
                pass
        self._invalidate_body_layout()

    def _sync_body_widget(self: Any) -> None:
        """Point the scroll widget at the current layout and repaint it."""
        try:
            widget = self._body_scroll()
        except Exception:
            return
        from sase.pager._screen_widgets import BODY_PAD_LEFT, BODY_PAD_RIGHT

        pads = BODY_PAD_LEFT + BODY_PAD_RIGHT
        width = self._body_paint_width()
        body = self._body
        total = 0
        if body is not None:
            try:
                total = int(body.total_height)
            except Exception:
                total = 0
        try:
            # Virtual width is the full strip width (text plus baked side
            # pads), matching the old inner Static's content width.
            widget.virtual_size = Size(width + pads, max(total, 1))
        except Exception:
            pass
        try:
            widget.clear_strip_cache()
        except Exception:
            pass
        try:
            widget.refresh(layout=True)
        except Exception:
            pass

    def _restore_reading_anchor(self: Any, anchor: Any, *, scroll_y: int) -> None:
        """Restore *anchor* after layout; a newer layout or scroll wins."""
        composed = self._body
        if composed is None:
            return
        try:
            target = row_for_reading_anchor(composed, anchor)
        except Exception:
            return
        generation = int(getattr(self, "_body_generation", 0) or 0) + 1
        try:
            self._body_generation = generation
        except Exception:
            pass
        document = getattr(self, "document", None)
        call_after_refresh = getattr(self, "call_after_refresh", None)
        if not callable(call_after_refresh):
            return

        def restore_after_layout() -> None:
            try:
                try:
                    if not self.is_mounted:
                        return
                except Exception:
                    pass
                if getattr(self, "document", None) is not document:
                    return
                if self._body is not composed:
                    return
                if int(getattr(self, "_body_generation", 0) or 0) != generation:
                    return
                scroll = self._body_scroll()
                if int(scroll.scroll_y) != int(scroll_y):
                    return
                clamped = max(0, min(target, int(scroll.max_scroll_y)))
                scroll.scroll_to(y=clamped, animate=False, immediate=True)
                self._update_chrome_position()
            except Exception:
                return

        call_after_refresh(restore_after_layout)

    def _body_paint_width(self: Any) -> int:
        """Return the width the body rows actually paint into.

        The one-cell side pads are baked into the strips (matching the
        old inner Static's ``padding: 0 1``), so the text width is the
        scrollable content width minus those pads.
        """
        from sase.pager._screen_widgets import BODY_PAD_LEFT, BODY_PAD_RIGHT

        pads = BODY_PAD_LEFT + BODY_PAD_RIGHT
        scroll = self._body_scroll()
        try:
            region_width = int(scroll.scrollable_content_region.width)
        except Exception:
            region_width = 0
        if region_width > 0:
            return max(region_width - pads, 1)
        try:
            return max(int(scroll.size.width) - pads, 1)
        except Exception:
            return 1

    def _gutter_content_width(self: Any, paint_width: int) -> int:
        max_count = max(
            (
                logical_line_count(section.plain_text)
                for section in self.document.sections
            ),
            default=0,
        )
        return max(paint_width - gutter_width(max_count), 1)

    def _history_rail_styles(self: Any, styles: Any) -> dict[int, str] | None:
        """Return per-section gutter rail styles from each section's moment.

        Past pins get the past-accent rail, deleted subjects the muted
        deleted rail, and every other kind gets none.
        """
        states = getattr(self, "_history_states", None)
        if not states or styles is None:
            return None
        try:
            from sase.pager.history.moment import moment_for_state
        except Exception:
            return None
        rails: dict[int, str] = {}
        for index, section in enumerate(self.document.sections):
            state = states.get(section.identity)
            if state is None:
                continue
            try:
                moment = moment_for_state(state)
            except Exception:
                continue
            kind = getattr(moment, "kind", "") if moment is not None else ""
            if kind == "past":
                rails[index] = str(styles.rail_past)
            elif kind == "deleted":
                rails[index] = str(styles.rail_deleted)
        return rails or None

    def _build_label_layer(
        self: Any, width: int, hint_offset: int = 0
    ) -> PagerLabelLayer:
        if not self.links_enabled:
            self._label_window_scope = None
            return PagerLabelLayer(
                labels=(),
                hint_to_label_index={},
                labels_by_section=tuple(() for _section in self.document.sections),
                target_count=0,
                mode="document",
            )
        section_offsets = self._body.section_offsets if self._body is not None else ()
        wrap_width = self._gutter_content_width(width)
        layer = build_label_layer(
            self.document,
            width=wrap_width,
            section_offsets=section_offsets,
            dangling_refs=self._dangling_refs.keys(),
            is_dangling=self._is_target_dangling,
            hint_offset=hint_offset,
        )
        if layer.target_count <= PAGER_LABEL_TWO_KEY_CAPACITY:
            self._label_window_scope = None
            return layer

        scope = self._current_label_window_scope()
        return build_label_layer(
            self.document,
            width=wrap_width,
            window_scope=scope,
            section_offsets=section_offsets,
            dangling_refs=self._dangling_refs.keys(),
            is_dangling=self._is_target_dangling,
            hint_offset=hint_offset,
        )

    def _current_label_window_scope(self: Any) -> LabelWindowScope:
        scroll = self._body_scroll()
        viewport_height = max(int(scroll.size.height), 1)
        scroll_y = max(int(scroll.scroll_y), 0)
        scope = self._label_window_scope
        if (
            scope is not None
            and scope.start_row <= scroll_y
            and scroll_y + viewport_height <= scope.end_row
        ):
            return scope
        start = max(scroll_y - viewport_height, 0)
        end = scroll_y + viewport_height * 2
        scope = LabelWindowScope(start, max(end, start + 1))
        self._label_window_scope = scope
        return scope

    def _refresh_window_scoped_labels_if_needed(self: Any) -> None:
        layer = self._label_layer
        if layer is None or layer.mode != "window":
            return
        current_scope = self._label_window_scope
        if current_scope is self._current_label_window_scope():
            return
        self._invalidate_body_layout(relabel=True)
        self._update_footer()

    def _row_for_section_line(self: Any, section_index: int, line: int) -> int | None:
        body = self._body
        if body is None or not 0 <= section_index < len(body.section_line_rows):
            return None
        rows = body.section_line_rows[section_index]
        if line < 1 or line > len(rows):
            return None
        return rows[line - 1]

    def _last_row_for_section_line(
        self: Any, section_index: int, line: int
    ) -> int | None:
        body = self._body
        first = self._row_for_section_line(section_index, line)
        if body is None or first is None:
            return None
        rows = body.section_line_rows[section_index]
        if line < len(rows):
            return rows[line] - 1
        if section_index + 1 < len(body.section_offsets):
            return body.section_offsets[section_index + 1] - 1
        return max(body.total_height - 1, first)

    def _current_section_index(self: Any) -> int:
        offsets = self._body.section_offsets if self._body is not None else (0,)
        return current_section_index(offsets, int(self._body_scroll().scroll_y))

    def _current_section(self: Any) -> PagerSection:
        return self.document.sections[self._current_section_index()]


__all__ = ["PagerBodyMixin"]

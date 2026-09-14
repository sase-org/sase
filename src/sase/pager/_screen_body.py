"""Body layout, scrolling, and section-position helpers for ``PagerScreen``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.widgets import Static

from sase.pager._gutter import gutter_width, logical_line_count
from sase.pager._labels import (
    LabelWindowScope,
    PAGER_LABEL_TWO_KEY_CAPACITY,
    PagerLabel,
    PagerLabelLayer,
    build_label_layer,
)
from sase.pager._layout import ComposedBody, compose_body, current_section_index
from sase.pager._screen_widgets import PagerBodyScroll
from sase.pager.app import PendingAction
from sase.pager.document import PagerDocument, PagerSection


class PagerBodyMixin:
    """Own the width-cached composed body and scroll commands."""

    _body: ComposedBody | None
    _body_width: int | None
    _label_layer: PagerLabelLayer | None
    _label_window_scope: LabelWindowScope | None
    _label_pending_prefix: str
    _last_activated_label: PagerLabel | None
    _pending_action: PendingAction
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

        This is a scroll, not a screen swap - deliberately unlike
        ``ZoomPanelModal``'s ``ctrl+n``, because the pager is one continuous
        document rather than independently-loaded panels.
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
            self._body_width = None
            self._ensure_body()
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
        self._body_width = None
        self._label_layer = None
        self._ensure_body()

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

    def _ensure_body(self: Any) -> None:
        """Rebuild the composed body only when the body's width changed.

        Sections are frozen and already parsed once at document-construction
        time (``PagerSection.__post_init__``); this only recomputes the
        width-dependent layout - section row offsets and transition rules -
        per ``tui_perf`` rule 8.
        """
        width = self._body_paint_width()
        if self._body is not None and width == self._body_width:
            return
        self._body_width = width
        self._label_layer = self._build_label_layer(width)
        body = self._compose_body_at_width(width)
        self._body = body
        self.query_one("#pager-body", Static).update(body.renderable)
        if getattr(self, "_goto_active", False):
            self._update_goto_command()

    def _body_paint_width(self: Any) -> int:
        """Return the width the body Static actually paints into."""
        scroll = self._body_scroll()
        body = self.query_one("#pager-body", Static)
        padding = body.styles.padding
        horizontal = int(padding.left) + int(padding.right)
        region_width = int(scroll.scrollable_content_region.width)
        base = region_width if region_width > 0 else int(scroll.size.width)
        return max(base - horizontal, 1)

    def _gutter_content_width(self: Any, paint_width: int) -> int:
        max_count = max(
            (
                logical_line_count(section.plain_text)
                for section in self.document.sections
            ),
            default=0,
        )
        return max(paint_width - gutter_width(max_count), 1)

    def _compose_body_at_width(self: Any, width: int) -> ComposedBody:
        mark = getattr(self, "_goto_mark", None)
        accent = self._goto_accent_for_mark() if mark is not None else None
        return compose_body(
            self.document,
            width,
            label_layer=self._label_layer,
            pending_prefix=self._label_pending_prefix,
            prepared_sections=self._prepared_section_texts(),
            line_mark=mark,
            goto_accent=accent,
        )

    def _build_label_layer(self: Any, width: int) -> PagerLabelLayer:
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
        self._body_width = None
        self._ensure_body()
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

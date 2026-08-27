"""Sticky subject and footer chrome for ``PagerScreen``."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.pager._chrome import footer_legend, subject_line
from sase.pager._layout import current_section_index


class PagerChromeMixin:
    """Render the visible pager chrome around the scrollable body."""

    def _set_footer_status(self: Any, status: str | None) -> None:
        self._footer_status = status
        self._update_footer()

    def _visible_label_count(self: Any) -> int:
        if self._label_layer is None:
            return 0
        return self._label_layer.visible_label_count

    def _update_footer(self: Any) -> None:
        self.query_one("#pager-footer", Static).update(
            footer_legend(
                section_total=len(self.document.sections),
                label_count=self._visible_label_count(),
                pending_prefix=self._label_pending_prefix,
                pending_action=self._pending_action,
                trail_back_count=len(self._back_trail),
                trail_forward_count=len(self._forward_trail),
                status=self._footer_status,
            )
        )

    def _update_subject(self: Any) -> None:
        scroll = self._body_scroll()
        total = len(self.document.sections)
        width = max(scroll.size.width, 1)
        subject_widget = self.query_one("#pager-subject", Static)
        if total == 0:
            subject_widget.update(Text(self.document.title, style="bold"))
            return

        offsets = self._body.section_offsets if self._body is not None else (0,)
        index = current_section_index(offsets, int(scroll.scroll_y))
        section = self.document.sections[index]
        percent = (
            100
            if scroll.max_scroll_y <= 0
            else min(100, round(scroll.scroll_y / scroll.max_scroll_y * 100))
        )
        char_count = sum(len(part.plain_text) for part in self.document.sections)
        subject_widget.update(
            subject_line(
                self.document,
                section,
                section_index=index + 1,
                section_total=total,
                scroll_percent=percent,
                char_count=char_count,
                width=width,
            )
        )


__all__ = ["PagerChromeMixin"]

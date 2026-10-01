"""Sticky subject and footer chrome for ``PagerScreen``."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.pager._chrome import footer_legend, subject_line
from sase.pager._layout import current_section_index
from sase.pager.syntax_theme import contrast_ratio, history_palette_from_theme


def _history_past_style(theme: object | None) -> str:
    """Return the contrast-checked past accent for the current host theme."""
    palette = history_palette_from_theme(theme)
    past = str(palette.get("past", "#9d7cd8"))
    try:
        if contrast_ratio(past, "#000000") < 3.0:
            return "#9d7cd8"
    except Exception:
        return "#9d7cd8"
    return past


class PagerChromeMixin:
    """Render the visible pager chrome around the scrollable body."""

    def _set_footer_status(self: Any, status: str | None) -> None:
        self._footer_status = status
        self._update_footer()

    def _visible_label_count(self: Any) -> int:
        if self._label_layer is None:
            return 0
        return self._label_layer.visible_label_count

    def _history_chrome_state(self: Any) -> tuple[bool, bool, dict[str, object] | None]:
        states = getattr(self, "_history_states", None)
        if not states:
            return (False, False, None)
        _ = _history_past_style(getattr(self, "_current_syntax_theme", lambda: None)())
        try:
            section = self._current_section()
        except Exception:
            return (False, False, None)
        state = states.get(section.identity)
        if state is None:
            return (False, False, None)
        pin = state.current_pin or section.version_pin
        ordinal = pin.ordinal if pin is not None else 0
        total = len(state.visible_ordinals)
        view = str(getattr(pin, "view", "read") or "read")
        history_state: dict[str, object] = {
            "ordinal": ordinal,
            "total": total,
            "dirty": state.status == "dirty-now",
            "tombstone": state.status == "tombstone",
            "age": "",
            "view": view,
            "diff_base": self._history_diff_base_for(state, ordinal),
        }
        return (True, ordinal > 0, history_state)

    def _history_diff_base_for(self: Any, state: Any, ordinal: int) -> int | None:
        try:
            from sase.pager.history.diff import diff_endpoints
        except Exception:
            return None
        try:
            pin = state.current_pin
            compare_base = getattr(pin, "compare_base", None)
            base_override = int(compare_base) if compare_base is not None else None
        except (TypeError, ValueError):
            base_override = None
        try:
            endpoints = diff_endpoints(
                ordinal=ordinal,
                visible_ordinals=tuple(state.visible_ordinals),
                dirty=bool(state.status == "dirty-now"),
                compare_base=base_override,
            )
        except Exception:
            return None
        return None if endpoints is None else endpoints[0]

    def _update_footer(self: Any) -> None:
        available, pinned, history_state = self._history_chrome_state()
        diff_view = (
            isinstance(history_state, dict)
            and str(history_state.get("view", "read")) == "diff"
        )
        self.query_one("#pager-footer", Static).update(
            footer_legend(
                section_total=len(self.document.sections),
                label_count=self._visible_label_count(),
                pending_prefix=self._label_pending_prefix,
                pending_action=self._pending_action,
                trail_back_count=len(self._back_trail),
                trail_forward_count=len(self._forward_trail),
                status=self._footer_status,
                history_available=available,
                history_pinned=pinned,
                history_diff_view=diff_view,
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
        composed = 0 if self._body is None else self._body.total_height
        fits = composed <= max(int(scroll.size.height), 1)
        percent = (
            100
            if fits or scroll.max_scroll_y <= 0
            else min(100, round(scroll.scroll_y / scroll.max_scroll_y * 100))
        )
        char_count = sum(len(part.plain_text) for part in self.document.sections)
        _, _, history_state = self._history_chrome_state()
        subject_widget.update(
            subject_line(
                self.document,
                section,
                section_index=index + 1,
                section_total=total,
                scroll_percent=percent,
                char_count=char_count,
                width=width,
                syntax_hint=self._current_syntax_hint(),
                history_state=history_state,
            )
        )


__all__ = ["PagerChromeMixin"]

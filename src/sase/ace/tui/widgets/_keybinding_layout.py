"""Layout and widget-update helpers for :class:`KeybindingFooter`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static


_MODE_BADGE_STYLE = "bold black on #FFD700"
# `padding: 0 1` on the footer + the 1-cell gutter between content and
# status that Textual leaves between the two flex children.
_CONTENT_RESERVED_CELLS = 2


class KeybindingLayoutMixin:
    """Binding-chip layout and cached ``Static.update`` behavior."""

    if TYPE_CHECKING:
        _last_bindings_signature: tuple[Any, ...] | None
        _last_status_signature: tuple[Any, ...] | None
        _last_layout_inputs: tuple[list[tuple[str, str]], str | None] | None
        _content_widget: Static | None
        _status_widget: Static | None
        size: Any

        def _get_status_text(self) -> Text: ...

        def _status_signature(self) -> tuple[Any, ...]: ...

        def _sorted_bindings(
            self,
            bindings: list[tuple[str, str]],
        ) -> list[tuple[str, str]]: ...

        def _format_bindings_inline(
            self,
            bindings: list[tuple[str, str]],
        ) -> Text: ...

        def _format_bindings_grid(
            self,
            bindings: list[tuple[str, str]],
            *,
            columns: int,
        ) -> Text: ...

        def _chip_plain_width(self, key: str, label: str) -> int: ...

    def _resolve_status_widget(self) -> Static | None:
        if self._status_widget is not None:
            return self._status_widget
        try:
            query_one = cast(Any, self).query_one
            self._status_widget = query_one("#keybinding-status", Static)
        except Exception:
            return None
        return self._status_widget

    def _resolve_content_widget(self) -> Static | None:
        if self._content_widget is not None:
            return self._content_widget
        try:
            query_one = cast(Any, self).query_one
            self._content_widget = query_one("#keybinding-content", Static)
        except Exception:
            return None
        return self._content_widget

    @staticmethod
    def _render_mode_badge(label: str) -> Text:
        """Mode prefix rendered as a filled pill badge.

        Pulls the mode word (``LEADER``, ``FOLD``, …) out of the binding flow
        so it never reads as another binding label, especially after wrap.
        """
        badge = Text(no_wrap=True)
        badge.append(f" {label} ", style=_MODE_BADGE_STYLE)
        return badge

    def _available_content_width(self) -> int:
        """Cells available to the bindings column on the current footer width.

        Returns 0 when the widget is not yet mounted / sized — callers
        treat this as "width unknown" and fall back to inline mode.
        """
        content = self._resolve_content_widget()
        if content is not None and content.size.width > 0:
            return int(content.size.width)
        try:
            footer_width = int(self.size.width)
        except Exception:
            footer_width = 0
        if footer_width <= 0:
            return 0
        status_w = cell_len(self._get_status_text().plain)
        return max(0, footer_width - status_w - _CONTENT_RESERVED_CELLS)

    def _layout(
        self,
        bindings: list[tuple[str, str]],
        mode_label: str | None,
    ) -> Text:
        """Decide between inline and grid layouts and return the rendered Text.

        The mode badge anchors the top-left in both layouts. In grid mode it
        sits on its own row so the chips can flow left-to-right starting at
        the same column.
        """
        sorted_b = self._sorted_bindings(bindings)
        inline_chips = self._format_bindings_inline(sorted_b)
        badge: Text | None = self._render_mode_badge(mode_label) if mode_label else None

        available = self._available_content_width()

        # Single-line width = badge + (one space) + inline chips.
        inline_chips_width = cell_len(inline_chips.plain)
        badge_width = cell_len(badge.plain) + 1 if badge is not None else 0
        single_line_width = badge_width + inline_chips_width

        # Inline if width is unknown, fits, or there is nothing to flow.
        if available <= 0 or single_line_width <= available or not sorted_b:
            return self._compose_inline(badge, inline_chips)

        # Compute grid columns. If a single chip is wider than the budget,
        # fall back to inline and let Rich wrap the long chip itself.
        max_chip = max(self._chip_plain_width(k, lbl) for k, lbl in sorted_b)
        cell_width = max_chip + 2  # +2 column gap (matches _format_bindings_grid)
        if cell_width > available:
            return self._compose_inline(badge, inline_chips)
        columns = max(1, available // cell_width)
        grid = self._format_bindings_grid(sorted_b, columns=columns)
        return self._compose_grid(badge, grid)

    @staticmethod
    def _compose_inline(badge: Text | None, chips: Text) -> Text:
        out = Text(no_wrap=True)
        if badge is not None:
            out.append_text(badge)
            out.append(" ")
        out.append_text(chips)
        return out

    @staticmethod
    def _compose_grid(badge: Text | None, grid: Text) -> Text:
        out = Text(no_wrap=True)
        if badge is not None:
            out.append_text(badge)
            if len(grid.plain) > 0:
                out.append("\n")
        out.append_text(grid)
        return out

    def _update_display(
        self,
        bindings: list[tuple[str, str]],
        mode_label: str | None = None,
    ) -> None:
        """Lay out the bindings and refresh the content/status widgets.

        Skips the actual ``Static.update`` calls when the signatures of
        the bindings text and the status indicator both match the last
        render — j/k bursts on the same entry repaint zero times.

        Args:
            bindings: ``(key, label)`` pairs to display, unsorted.
            mode_label: Optional mode word (e.g. ``"LEADER"``) rendered as
                a pill badge anchoring the layout.
        """
        # Remember the inputs so ``on_resize`` can re-lay-out without state.
        self._last_layout_inputs = (list(bindings), mode_label)

        bindings_text = self._layout(bindings, mode_label)
        # ``Text`` carries spans we want to compare too; the rendered
        # ``__rich_console__`` output isn't readily available, so we hash
        # the plain text plus span tuples.
        bindings_signature = (
            bindings_text.plain,
            tuple((s.start, s.end, str(s.style)) for s in bindings_text.spans),
        )
        status_signature = self._status_signature()
        bindings_dirty = bindings_signature != self._last_bindings_signature
        status_dirty = status_signature != self._last_status_signature
        if not bindings_dirty and not status_dirty:
            return
        content = self._resolve_content_widget()
        status = self._resolve_status_widget()
        if bindings_dirty and content is not None:
            content.update(bindings_text)
            self._last_bindings_signature = bindings_signature
        if status_dirty and status is not None:
            status.update(self._get_status_text())
            self._last_status_signature = status_signature

"""Diff widgets and diff/read painting for the Memory panel card.

Split of :mod:`sase.ace.tui.modals.memory_panel_view`: this module owns
the diff ``(body, diff)`` widgets, the diff-ready check, and the
diff/read paint step behind
:class:`~sase.ace.tui.modals.memory_panel_view.MemoryPanelViewMixin`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Markdown, Static

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase
    from textual.widgets import OptionList

    from rich.console import RenderableType

    from sase.ace.tui.keymaps import MemoryPanelKeymaps
    from sase.ace.tui.memory_panel_catalog import (
        MemoryRailNode,
        MemoryScopeRef,
        MemoryScopeSnapshot,
    )
    from sase.memory.notes import MemoryNote
else:
    _MixinBase = object


class MemoryPanelViewDiffMixin(_MixinBase):
    """Diff widgets and the diff/read paint step."""

    if TYPE_CHECKING:
        _accent: str
        _all_rows: tuple[MemoryRailNode, ...]
        _chip_cursor: int | None
        _chip_notes: tuple[MemoryNote, ...]
        _chip_parent_count: int
        _current_note: str | None
        _filter_text: str
        _keymaps: MemoryPanelKeymaps
        _loading: bool
        _rows: tuple[MemoryRailNode, ...]
        _ring: tuple[MemoryScopeRef, ...]
        _scope_index: int
        _snapshot: MemoryScopeSnapshot | None
        _strand_read_status: dict[str, str]
        _trail: list[str]

        def _note_list(self) -> OptionList: ...

        def _scope_is_unpublished(self) -> bool: ...

        def _selected_is_writable(self) -> bool: ...

        def _card_moment(
            self, node: Any | None, *, applied: bool = True, view: str = "read"
        ) -> Any | None: ...

        def _diff_overlay_for_node(self, node: Any | None) -> Any | None: ...

        def _diff_text_for_node(self, node: Any | None) -> Any | None: ...

        def _diff_view_on(self) -> bool: ...

        def _ensure_diff(self, node: Any) -> bool: ...

        def _maybe_prefetch_at_now(self, node: Any | None) -> None: ...

        def _now_moment_for_footer(
            self, node: Any | None, *, view: str = "read"
        ) -> Any | None: ...

        def _past_card_for_node(self, node: Any | None) -> Any | None: ...

        def _selected_row(self) -> MemoryRailNode | None: ...

        def _time_applied_ordinal(self, node: Any | None) -> int: ...

        def _time_past_note(self, node: Any, body_text: str) -> Any | None: ...

        def _time_pinned_ordinal(self, node: Any | None) -> int: ...

        def _time_strip_snapshot_for_node(self, node: Any) -> Any | None: ...

        def _time_strip_styles(self) -> Any: ...

    def _diff_widgets_for_card(self) -> tuple[Any | None, Any | None]:
        """Return the ``(body, diff)`` card widgets, tolerating old mounts."""
        try:
            body_widget = self.query_one("#memory-panel-card-body", Markdown)
        except Exception:
            body_widget = None
        try:
            diff_widget = self.query_one("#memory-panel-card-diff", Static)
        except Exception:
            diff_widget = None
        return (body_widget, diff_widget)

    def _diff_show_for_node(self, node: Any) -> tuple[Any | None, Any | None]:
        """Return the ``(overlay, diff_text)`` when the diff is ready.

        ``None`` overlay means the card renders its read chrome: diff
        off, still loading (the read view stays on screen), or failed
        (the read view stays, with a toast already sent).
        """
        try:
            overlay = self._diff_overlay_for_node(node)
        except Exception:
            return (None, None)
        if overlay is None:
            return (None, None)
        try:
            text = self._diff_text_for_node(node)
        except Exception:
            text = None
        if text is None:
            return (None, None)
        return (overlay, text)

    def _paint_card_text(
        self, body_widget: Any | None, diff_widget: Any | None, diff_text: Any | None
    ) -> bool:
        """Show the diff widget or the read body; True when diff shows."""
        if diff_text is not None and diff_widget is not None:
            try:
                diff_widget.display = True
                diff_widget.update(diff_text)
            except Exception:
                pass
            if body_widget is not None:
                try:
                    body_widget.display = False
                except Exception:
                    pass
            return True
        if diff_widget is not None:
            try:
                diff_widget.display = False
                diff_widget.update("")
            except Exception:
                pass
        if body_widget is not None:
            try:
                body_widget.display = True
            except Exception:
                pass
        return False


__all__ = ["MemoryPanelViewDiffMixin"]

"""Header, footer, trail, and rail width for the Memory panel.

Split of :mod:`sase.ace.tui.modals.memory_panel_view`: this module owns
the panel chrome (loading header, header, footer, trail strip, and
note-rail width) behind
:class:`~sase.ace.tui.modals.memory_panel_view.MemoryPanelViewMixin`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import RenderableType
from rich.text import Text
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Static

from sase.ace.tui.keymaps.display import key_display_name
from .memory_panel_rendering import (
    build_panel_footer,
    build_panel_header,
    note_rail_width,
)
from .trail_strip import build_trail_strip

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


class MemoryPanelViewChromeMixin(_MixinBase):
    """Panel header, footer, trail strip, and note-rail width."""

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

    def _loading_header_text(self) -> Text:
        return Text("MEMORY  ·  loading…", style=f"bold {self._accent}")

    def _update_header(self) -> None:
        header: RenderableType
        if self._loading:
            header = self._loading_header_text()
        else:
            scope_display_name = (
                self._snapshot.scope.display_name if self._snapshot else ""
            )
            note_count = len(self._snapshot.notes) if self._snapshot else 0
            try:
                deleted_count = int(self._deleted_header_count())  # type: ignore[attr-defined]
            except Exception:
                deleted_count = 0
            header = build_panel_header(
                scope_display_name=scope_display_name,
                note_count=note_count,
                scope_index=self._scope_index,
                scope_count=len(self._ring),
                accent=self._accent,
                unpublished=self._scope_is_unpublished(),
                deleted_count=deleted_count,
            )
        self.query_one("#memory-panel-header", Static).update(header)

    def _resize_note_rail(self) -> None:
        """Fit the note rail to its widest row within the panel's width."""
        try:
            body = self.query_one("#memory-panel-body", Horizontal)
            note_list = self._note_list()
        except NoMatches:
            return
        generated_paths = (
            self._snapshot.generated_paths
            if self._snapshot is not None
            else frozenset()
        )
        try:
            glance_width = int(self._glance_column_width())  # type: ignore[attr-defined]
        except Exception:
            glance_width = 0
        width = note_rail_width(
            self._all_rows,
            generated_paths=generated_paths,
            available_width=body.size.width,
            glance_width=glance_width,
        )
        current = note_list.styles.width
        if current is not None and current.is_cells and int(current.value) == width:
            return
        note_list.styles.width = width

    def _update_footer(self) -> None:
        node = self._selected_row()
        focused_link_stem = None
        if self._chip_cursor is not None and 0 <= self._chip_cursor < len(
            self._chip_notes
        ):
            focused_link_stem = self._chip_notes[self._chip_cursor].path.stem
        pinned = self._time_applied_ordinal(node) > 0 if node is not None else False
        try:
            diff_on = bool(self._diff_view_on())
        except Exception:
            diff_on = False
        time_verbs: tuple[str, ...] = ()
        if node is not None and not self._loading:
            try:
                view = "diff" if diff_on else "read"
                moment = self._card_moment(node, view=view)
                if moment is None and not pinned:
                    moment = self._now_moment_for_footer(node, view=view)
                if moment is not None:
                    from .memory_pane_time import step_footer_verbs

                    time_verbs = step_footer_verbs(moment, keymaps=self._keymaps)
            except Exception:
                time_verbs = ()
        try:
            deleted_key = key_display_name(self._keymaps.toggle_deleted)
            deleted_verb = f"{deleted_key} deleted"
        except Exception:
            deleted_verb = ""
        footer = build_panel_footer(
            self._keymaps,
            has_notes=bool(self._rows),
            has_source_path=node is not None,
            ring_size=len(self._ring),
            has_links=bool(self._chip_notes),
            has_trail=bool(self._trail),
            focused_link_stem=focused_link_stem,
            web_action=self._web_footer_action(node),
            has_strand_navigation=bool(
                node is not None and node.web is not None and node.web.strands
            ),
            can_mutate=self._selected_is_writable() and not pinned,
            unpublished=self._scope_is_unpublished() and not pinned,
            time_verbs=time_verbs,
            edit_now=pinned,
            deleted_verb=deleted_verb if bool(self._rows) else "",
        )
        footer_widget = self.query_one("#memory-panel-footer", Static)
        footer_widget.update(footer)
        footer_widget.display = bool(footer)

    def _trail_strip(self) -> Static:
        return self.query_one("#memory-panel-trail", Static)

    def _update_trail_strip(self) -> None:
        trail_widget = self._trail_strip()
        if not self._trail or self._current_note is None:
            trail_widget.display = False
            trail_widget.update("")
            return
        trail_widget.display = True
        labels = tuple(Path(path).stem for path in (*self._trail, self._current_note))
        trail_widget.update(build_trail_strip(labels, accent=self._accent))

    def _web_footer_action(self, node: MemoryRailNode | None) -> str | None:
        if node is None or node.web is None:
            return None
        if node.is_strand:
            return "collapse web"
        return "collapse" if node.expanded else "expand"


__all__ = ["MemoryPanelViewChromeMixin"]

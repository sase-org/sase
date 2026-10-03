"""Note-card rendering and body previews for the Memory panel.

Split of :mod:`sase.ace.tui.modals.memory_panel_view`: this module owns
the note-card paint (read, past, and instruction branches) and the body
preview behind
:class:`~sase.ace.tui.modals.memory_panel_view.MemoryPanelViewMixin`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

from .memory_panel_rendering import (
    build_diagnostics_message,
    build_empty_scope_message,
    build_empty_scope_no_root_message,
    build_no_match_message,
    build_rail_node_description,
)
from .memory_panel_web_rendering import build_rail_node_card_meta

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


class MemoryPanelViewCardMixin(_MixinBase):
    """Note-card rendering and body previews."""

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

        def _diff_show_for_node(self, node: Any) -> tuple[Any | None, Any | None]: ...

        def _diff_view_on(self) -> bool: ...

        def _diff_widgets_for_card(self) -> tuple[Any | None, Any | None]: ...

        def _ensure_diff(self, node: Any) -> bool: ...

        def _maybe_prefetch_at_now(self, node: Any | None) -> None: ...

        def _now_moment_for_footer(
            self, node: Any | None, *, view: str = "read"
        ) -> Any | None: ...

        def _paint_card_text(
            self,
            body_widget: Any | None,
            diff_widget: Any | None,
            diff_text: Any | None,
        ) -> bool: ...

        def _past_card_for_node(self, node: Any | None) -> Any | None: ...

        def _pinned_head_for_node(
            self, node: MemoryRailNode, *, snapshot_scope: Any, past: Any = None
        ) -> RenderableType: ...

        def _selected_row(self) -> MemoryRailNode | None: ...

        def _time_applied_ordinal(self, node: Any | None) -> int: ...

        def _time_past_note(self, node: Any, body_text: str) -> Any | None: ...

        def _time_pinned_ordinal(self, node: Any | None) -> int: ...

        def _time_strip_snapshot_for_node(self, node: Any) -> Any | None: ...

        def _time_strip_styles(self) -> Any: ...

        def _update_footer(self) -> None: ...

        def _update_time_frame(self, node: Any) -> None: ...

        def _update_time_strip(
            self, node: MemoryRailNode, strip_widget: Any, past: Any = None
        ) -> None: ...

        def _update_trail_strip(self) -> None: ...

    def _render_note_card(self) -> None:
        self._update_trail_strip()
        title_widget = self.query_one("#memory-panel-card-title", Static)
        try:
            strip_widget = self.query_one("#memory-panel-time-strip", Static)
        except Exception:
            strip_widget = None
        description_widget = self.query_one("#memory-panel-card-description", Static)
        body_widget, diff_widget = self._diff_widgets_for_card()
        meta_widget = self.query_one("#memory-panel-card-meta", Static)

        def _hide_strip() -> None:
            if strip_widget is not None:
                try:
                    strip_widget.display = False
                    strip_widget.update("")
                except Exception:
                    pass

        def _body(text: str) -> None:
            if body_widget is not None:
                try:
                    body_widget.display = True
                    body_widget.update(text)
                except Exception:
                    pass
            if diff_widget is not None:
                try:
                    diff_widget.display = False
                except Exception:
                    pass

        if self._loading:
            title_widget.update("")
            _hide_strip()
            description_widget.update("")
            _body("Loading…")
            meta_widget.update("")
            return

        snapshot = self._snapshot
        if snapshot is None or not self._ring:
            title_widget.update("")
            _hide_strip()
            description_widget.update("")
            _body("No memory scopes are available.")
            meta_widget.update("")
            return

        if snapshot.diagnostics:
            title_widget.update("")
            _hide_strip()
            description_widget.update("")
            _body("")
            meta_widget.update(
                build_diagnostics_message(snapshot.diagnostics, accent=self._accent)
            )
            return

        if not snapshot.notes:
            title_widget.update("")
            _hide_strip()
            description_widget.update("")
            _body("")
            if snapshot.scope.memory_read_root is None:
                meta_widget.update(
                    build_empty_scope_no_root_message(
                        snapshot.scope.display_name, accent=self._accent
                    )
                )
            else:
                meta_widget.update(
                    build_empty_scope_message(
                        snapshot.scope.display_name, accent=self._accent
                    )
                )
            return

        node = self._selected_row()
        if node is None:
            title_widget.update("")
            _hide_strip()
            description_widget.update("")
            _body("")
            if self._filter_text:
                meta_widget.update(build_no_match_message(self._filter_text))
            else:
                meta_widget.update("")
            return

        overlay, diff_text = self._diff_show_for_node(node)
        if overlay is None and diff_text is None:
            # Diff on but not ready: kick the render-path load so the
            # read view swaps as soon as the worker lands.
            try:
                if self._diff_view_on():
                    self._ensure_diff(node)
            except Exception:
                pass
        past = self._past_card_for_node(node)
        if past is not None and past.body_text is not None:
            self._render_past_card(
                node,
                past,
                snapshot,
                title_widget,
                strip_widget,
                description_widget,
                body_widget,
                diff_widget,
                meta_widget,
                diff_chrome=overlay,
                diff_text=diff_text,
            )
            self._update_time_frame(node)
            self._update_footer()
            return
        self._update_time_frame(node)
        try:
            self._maybe_prefetch_at_now(node)
        except Exception:
            pass
        title_widget.update(
            self._pinned_head_for_node(node, snapshot_scope=snapshot, past=overlay)
        )
        self._update_time_strip(node, strip_widget, past=overlay)
        try:
            from .memory_pane_instructions import (
                build_instruction_card_meta as _build_instruction_meta,
            )
            from .memory_pane_instructions import (
                is_instruction_group_row as _is_instruction_group,
            )
            from .memory_pane_instructions import (
                is_instruction_subject_row as _is_instruction_row,
            )

            _instruction_subject = None
            _instruction_kind = (
                "group"
                if _is_instruction_group(node)
                else ("row" if _is_instruction_row(node) else "")
            )
            if _instruction_kind == "row":
                try:
                    _instruction_subject = self._instruction_subject_for_node(node)  # type: ignore[attr-defined]
                except Exception:
                    _instruction_subject = None
        except Exception:
            _instruction_kind = ""
            _instruction_subject = None
        if _instruction_kind:
            description_widget.update("")
        else:
            description_widget.update(build_rail_node_description(node))
        if not self._paint_card_text(body_widget, diff_widget, diff_text):
            _body(self._body_preview_for_node(node))
        if _instruction_kind == "group":
            try:
                _group_count = len(self._instruction_order)  # type: ignore[attr-defined]
            except Exception:
                _group_count = 0
            meta_widget.update(
                Text(
                    f"{_group_count} instruction files · space expands · collapses",
                    style="dim",
                )
            )
            self._update_footer()
            return
        if _instruction_kind == "row" and _instruction_subject is not None:
            meta_widget.update(
                _build_instruction_meta(_instruction_subject, accent=self._accent)
            )
            self._update_footer()
            return
        parent = self._chip_notes[: self._chip_parent_count]
        children = self._chip_notes[self._chip_parent_count :]
        focused_link_number = (
            self._chip_cursor + 1 if self._chip_cursor is not None else None
        )
        meta_widget.update(
            build_rail_node_card_meta(
                snapshot,
                node,
                accent=self._accent,
                parent=parent,
                children=children,
                focused_link_number=focused_link_number,
                strand_read_state=self._strand_read_status.get(node.identity),
            )
        )
        self._update_footer()

    def _render_past_card(
        self,
        node: MemoryRailNode,
        past: Any,
        snapshot: Any,
        title_widget: Static,
        strip_widget: Any,
        description_widget: Static,
        body_widget: Any | None,
        diff_widget: Any | None,
        meta_widget: Static,
        *,
        diff_chrome: Any | None = None,
        diff_text: Any | None = None,
    ) -> None:
        """Paint one past version: past pill, strip, frame, body, footer.

        When the sticky diff view is ready, *diff_chrome* (a diff-view
        kit moment overlay) drives the pill, context, and strip, and
        *diff_text* replaces the body; otherwise the read view renders.
        """
        from dataclasses import replace as _replace

        from rich.console import Group

        chrome = diff_chrome if diff_chrome is not None else past
        past_note = self._time_past_note(node, past.body_text or "")
        past_node = node
        if past_note is not None:
            try:
                past_node = _replace(node, note=past_note)
            except Exception:
                past_node = node
        title_widget.update(
            self._pinned_head_for_node(node, snapshot_scope=snapshot, past=chrome)
        )
        self._update_time_strip(node, strip_widget, past=chrome)
        try:
            from .memory_pane_instructions import (
                is_instruction_subject_row as _is_past_instruction,
            )

            _past_is_instruction = _is_past_instruction(node)
        except Exception:
            _past_is_instruction = False
        if _past_is_instruction:
            description_widget.update("")
        else:
            description_widget.update(build_rail_node_description(past_node))
        if self._paint_card_text(body_widget, diff_widget, diff_text):
            pass
        elif past_note is not None:
            body_text = past_note.body
            if body_widget is not None:
                try:
                    body_widget.update(
                        body_text if body_text.strip() else "_No body content._"
                    )
                except Exception:
                    pass
        elif body_widget is not None:
            try:
                body_widget.update(past.body_text or "")
            except Exception:
                pass
        parent = self._chip_notes[: self._chip_parent_count]
        children = self._chip_notes[self._chip_parent_count :]
        focused_link_number = (
            self._chip_cursor + 1 if self._chip_cursor is not None else None
        )
        _past_instruction_subject = None
        if _past_is_instruction:
            try:
                _past_instruction_subject = self._instruction_subject_for_node(node)  # type: ignore[attr-defined]
            except Exception:
                _past_instruction_subject = None
        if _past_instruction_subject is not None:
            from .memory_pane_instructions import (
                build_instruction_card_meta as _build_past_instruction_meta,
            )

            meta = _build_past_instruction_meta(
                _past_instruction_subject, accent=self._accent
            )
        else:
            meta = build_rail_node_card_meta(
                snapshot,
                past_node,
                accent=self._accent,
                parent=parent,
                children=children,
                focused_link_number=focused_link_number,
                strand_read_state=None,
            )
        # Relation chips are computed from today's graph, so they read
        # under an explicit `links as of now` caption.
        if parent or children:
            meta_widget.update(Group(Text("links as of now", style="dim"), meta))
        else:
            meta_widget.update(meta)

    def _body_preview_for_node(self, node: MemoryRailNode) -> str:
        try:
            past = self._past_card_for_node(node)
        except Exception:
            past = None
        if past is not None:
            # A pinned strand shows its historical body without writing
            # an audited read; the past branch renders notes directly.
            if past.body_text is None:
                return "_Loading past version..._"
            try:
                past_note = self._time_past_note(node, past.body_text)
                if past_note is not None:
                    body = past_note.body
                    return body if body.strip() else "_No body content._"
                return past.body_text
            except Exception:
                return past.body_text or ""
        if not node.is_strand:
            return node.note.body if node.note.body.strip() else "_No body content._"
        state = self._strand_read_status.get(node.identity)
        if state == "ok":
            return node.note.body if node.note.body.strip() else "_No body content._"
        if state == "pending" or state is None:
            return "_Recording audited read before previewing this strand..._"
        if state.startswith("error:"):
            return f"_Could not record audited read: {state.removeprefix('error:')}_"
        return "_Could not record audited read._"


__all__ = ["MemoryPanelViewCardMixin"]

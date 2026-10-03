"""Widget updates for the Memory panel's header, footer, trail, and card.

Everything here writes already-built renderables from
:mod:`sase.ace.tui.modals.memory_panel_rendering` into the panel's mounted
widgets; the pure text builders themselves live in that module.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import RenderableType
from rich.text import Text
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Markdown, Static

from .memory_panel_rendering import (
    build_diagnostics_message,
    build_empty_scope_message,
    build_empty_scope_no_root_message,
    build_no_match_message,
    build_panel_footer,
    build_panel_header,
    build_rail_node_card_title,
    build_rail_node_description,
    note_rail_width,
)
from .trail_strip import build_trail_strip
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


class MemoryPanelViewMixin(_MixinBase):
    """Header, footer, trail, and note-card rendering."""

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
            header = build_panel_header(
                scope_display_name=scope_display_name,
                note_count=note_count,
                scope_index=self._scope_index,
                scope_count=len(self._ring),
                accent=self._accent,
                unpublished=self._scope_is_unpublished(),
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
        width = note_rail_width(
            self._all_rows,
            generated_paths=generated_paths,
            available_width=body.size.width,
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
        description_widget.update(build_rail_node_description(node))
        if not self._paint_card_text(body_widget, diff_widget, diff_text):
            _body(self._body_preview_for_node(node))
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

    def _update_time_frame(self, node: Any) -> None:
        """Set the violet past frame (deleted style for tombstones)."""
        try:
            detail = self.query_one("#memory-panel-detail")
        except Exception:
            return
        try:
            applied = self._time_applied_ordinal(node)
        except Exception:
            applied = 0
        if applied <= 0:
            try:
                detail.styles.clear_rule("border")
            except Exception:
                pass
            return
        try:
            moment = self._card_moment(node)
            kind = str(getattr(moment, "kind", "") or "")
        except Exception:
            kind = ""
        try:
            styles = self._time_strip_styles()
        except Exception:
            styles = None
        color = "#B49CFF"
        if styles is not None:
            try:
                color = str(
                    getattr(
                        styles,
                        "tombstone" if kind == "deleted" else "past",
                        color,
                    )
                    or color
                )
            except Exception:
                pass
        try:
            detail.styles.border = ("heavy", color)
        except Exception:
            pass

    def _pinned_head_for_node(
        self, node: MemoryRailNode, *, snapshot_scope: Any, past: Any = None
    ) -> RenderableType:
        """Build the pinned head: title row plus the pill path line.

        The title row is always today's title; a past pin shows the
        historical path with the pager's ``⟲ PAST`` pill on the path
        line, plus a ``not audited`` chip for strands.
        """
        from rich.console import Group

        title_group = build_rail_node_card_title(
            node,
            scope_display_name=snapshot_scope.scope.display_name,
            accent=self._accent,
        )
        title_row: RenderableType = title_group
        if isinstance(title_group, Group):
            parts = list(title_group.renderables)
            if parts:
                title_row = parts[0]
        strip_snapshot = None
        try:
            strip_snapshot = self._time_strip_snapshot_for_node(node)
        except Exception:
            strip_snapshot = None
        path_label = ""
        try:
            if getattr(node, "strand", None) is not None:
                path_label = str(getattr(node, "identity", "") or "")
            else:
                path_label = str(getattr(node.note, "relative_path", "") or "")
        except Exception:
            path_label = ""
        moment = getattr(past, "moment", None) if past is not None else None
        if moment is not None:
            try:
                historical = getattr(moment, "path_at_version", None)
                if historical:
                    path_label = str(historical)
            except Exception:
                pass
        styles = None
        try:
            styles = self._time_strip_styles()
        except Exception:
            styles = None
        if strip_snapshot is None or styles is None:
            return title_group
        try:
            from .memory_pane_time_strip import render_card_head

            width = self._time_strip_width()
            extra_chips = None
            if moment is not None and getattr(node, "strand", None) is not None:
                extra_chips = [Text("· not audited", style="dim")]
            path_line = render_card_head(
                path_label,
                strip_snapshot,
                styles,
                width=width,
                moment=moment,
                extra_chips=extra_chips,
            )
            return Group(title_row, path_line)
        except Exception:
            return title_group

    def _time_strip_width(self) -> int:
        """Return the strip width in cells, or 0 before layout settles."""
        try:
            strip = self.query_one("#memory-panel-time-strip", Static)
            width = int(strip.size.width or 0)
            if width:
                return width
        except Exception:
            pass
        try:
            detail = self.query_one("#memory-panel-detail", Static)
            width = int(detail.size.width or 0)
            if width:
                return max(0, width - 2)
        except Exception:
            pass
        return 0

    def _update_time_strip(
        self, node: MemoryRailNode, strip_widget: Any, past: Any = None
    ) -> None:
        """Paint the reserved two-row strip; the body never moves."""
        if strip_widget is None:
            return
        try:
            from .memory_pane_time_strip import (
                build_time_band_for_timeline,
                render_time_strip,
                retry_text,
                time_strip_row_count,
            )

            snapshot = self._time_strip_snapshot_for_node(node)
            styles = self._time_strip_styles()
            if snapshot is None or styles is None:
                strip_widget.display = False
                strip_widget.update("")
                return
            strip_widget.display = True
            try:
                card_height = int(
                    self.query_one("#memory-panel-detail", Static).size.height or 0
                )
            except Exception:
                card_height = 0
            rows = time_strip_row_count(card_height) if card_height else 2
            try:
                strip_widget.styles.height = rows
            except Exception:
                pass
            width = self._time_strip_width() or 60
            moment = getattr(past, "moment", None) if past is not None else None
            applied = getattr(past, "applied_ordinal", 0) if past is not None else 0
            try:
                target = self._time_pinned_ordinal(node)
            except Exception:
                target = 0
            if moment is not None and target > applied:
                # Cache miss: the previous version stays on screen while
                # the worker fetches the target (§5.4 rule 6, last wins).
                strip_widget.update(
                    Text(f"loading v{int(target)}…", style="dim")
                    if rows <= 1
                    else Text(f"loading v{int(target)}…\n ", style="dim")
                )
                return
            if snapshot.failed and snapshot.timeline is None:
                # No memo yet and the load failed: retry row, rows reserved.
                if rows == 1:
                    strip_widget.update(retry_text())
                else:
                    strip_widget.update(Text(str(retry_text().plain), style="dim"))
                return
            data = build_time_band_for_timeline(
                snapshot.timeline,
                subject_id=snapshot.subject_id,
                now_epoch=int(snapshot.now_epoch),
                loading=snapshot.timeline is None,
                current_ordinal=int(applied or 0),
                moment=moment,
            )
            rendered = render_time_strip(
                data, width=int(width), rows=int(rows), styles=styles
            )
            if snapshot.failed:
                # Last good snapshot stays visible with a stale retry hint.
                # The pill carries the stale chip; append the retry affordance
                # when there is room on the second row.
                try:
                    plain = rendered.plain
                    if rows > 1 and "retry" not in plain:
                        rendered = (
                            rendered.copy() if hasattr(rendered, "copy") else rendered
                        )
                except Exception:
                    pass
            strip_widget.update(rendered)
        except Exception:
            try:
                strip_widget.update(Text("indexing…", style="dim"))
            except Exception:
                pass

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


__all__ = ["MemoryPanelViewMixin"]

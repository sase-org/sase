"""Past frame, pinned head, and time strip for the Memory panel card.

Split of :mod:`sase.ace.tui.modals.memory_panel_view`: this module owns
the violet past frame, the pinned title head, the strip width, and the
reserved two-row time strip behind
:class:`~sase.ace.tui.modals.memory_panel_view.MemoryPanelViewMixin`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import RenderableType
from rich.text import Text
from textual.widgets import Static

from .memory_panel_rendering import build_rail_node_card_title

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


class MemoryPanelViewTimeMixin(_MixinBase):
    """Past frame, pinned head, strip width, and time strip."""

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
        try:
            from .memory_pane_instructions import (
                build_instruction_card_title,
                build_instruction_group_card_title,
                is_instruction_group_row,
                is_instruction_subject_row,
            )

            if is_instruction_group_row(node):
                try:
                    group_count = len(self._instruction_order)  # type: ignore[attr-defined]
                except Exception:
                    group_count = 0
                title_group = build_instruction_group_card_title(
                    group_count,
                    scope_display_name=snapshot_scope.scope.display_name,
                    accent=self._accent,
                )
            elif is_instruction_subject_row(node):
                display = ""
                path_label = ""
                try:
                    subject = self._instruction_subject_for_node(node)  # type: ignore[attr-defined]
                except Exception:
                    subject = None
                if subject is not None:
                    display = str(subject.display or subject.path)
                    path_label = str(subject.path)
                if not display:
                    try:
                        display = str(node.note.path.stem)
                        path_label = str(node.note.relative_path)
                    except Exception:
                        display, path_label = ("AGENTS.md", "AGENTS.md")
                title_group = build_instruction_card_title(
                    display,
                    path_label,
                    scope_display_name=snapshot_scope.scope.display_name,
                    accent=self._accent,
                )
        except Exception:
            pass
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


__all__ = ["MemoryPanelViewTimeMixin"]

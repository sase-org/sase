"""Snapshot, filter, and note-selection state for the Memory panel.

This is the panel's core state machine: it turns a loaded scope snapshot
into the filtered note tree, keeps the ``OptionList`` highlight anchored to
the same note across reloads and filter edits, and answers "which note is
selected?" for every other mixin.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from sase.ace.tui.memory_panel_catalog import MemoryRailNode, memory_strand_note
from sase.ace.tui.util.selection import restore_selection_by_identity
from sase.memory.text_filter import filter_memory_notes
from sase.memory.web.models import WebScope

from .memory_panel_rendering import build_note_row_text

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase

    from sase.ace.tui.memory_panel_catalog import MemoryScopeSnapshot
    from sase.ace.tui.util.debounce import DetailPanelDebouncer
    from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
else:
    _MixinBase = object

_NOTE_LIST_ID = "memory-panel-notes"
_FILTER_INPUT_ID = "memory-panel-filter"


class MemoryPanelStateMixin(_MixinBase):
    """Snapshot application, filtering, and selection for :class:`MemoryPane`."""

    if TYPE_CHECKING:
        _all_rows: tuple[MemoryRailNode, ...]
        _current_note: str | None
        _debouncer: DetailPanelDebouncer | None
        _filter_bodies: bool
        _filter_text: str
        _rows: tuple[MemoryRailNode, ...]
        _expanded_webs: set[str]
        _selection_guard: ProgrammaticSelectionGuard
        _ring: tuple[Any, ...]
        _scope_index: int
        _snapshot: MemoryScopeSnapshot | None
        _unpublished_scopes: set[str]

        def _ensure_strand_read_for_current_selection(self) -> None: ...

        def _refresh_links_for_current_note(self) -> None: ...

        def _render_note_card(self) -> None: ...

        def _resize_note_rail(self) -> None: ...

        def _update_footer(self) -> None: ...

        def _update_header(self) -> None: ...

        def _record_session_selection(self) -> None: ...

        def _reset_strand_read_state(self) -> None: ...

    def _apply_snapshot(
        self, snapshot: MemoryScopeSnapshot | None, *, preferred_note: str | None
    ) -> None:
        self._reset_strand_read_state()
        self._snapshot = snapshot
        self._all_rows = self._expanded_rows(snapshot) if snapshot is not None else ()
        self._resize_note_rail()
        self._apply_filter(
            self._filter_text,
            include_bodies=self._filter_bodies,
            preferred_note=preferred_note,
        )

    def _expanded_rows(
        self, snapshot: MemoryScopeSnapshot
    ) -> tuple[MemoryRailNode, ...]:
        rows: list[MemoryRailNode] = []
        strand_scope: WebScope = "home" if snapshot.scope.kind == "home" else "project"
        for node in snapshot.tree:
            if node.web is None:
                rows.append(node)
                continue
            expanded = node.web.slug in self._expanded_webs
            rows.append(replace(node, expanded=expanded))
            if not expanded:
                continue
            rows.extend(
                MemoryRailNode(
                    note=memory_strand_note(node.web, strand),
                    depth=node.depth + 1,
                    web=node.web,
                    strand=strand,
                    strand_scope=strand_scope,
                )
                for strand in node.web.strands
            )
        return tuple(rows)

    def _refresh_expanded_rows(self, *, preferred_note: str | None = None) -> None:
        if self._snapshot is None:
            return
        self._all_rows = self._expanded_rows(self._snapshot)
        self._resize_note_rail()
        self._apply_filter(
            self._filter_text,
            include_bodies=self._filter_bodies,
            preferred_note=preferred_note,
        )

    def _apply_filter(
        self,
        pattern: str,
        *,
        include_bodies: bool,
        preferred_note: str | None = None,
    ) -> None:
        self._filter_text = pattern
        self._filter_bodies = include_bodies
        matched_paths = {
            note.relative_path
            for note in filter_memory_notes(
                (node.note for node in self._all_rows),
                pattern=pattern or None,
                include_bodies=include_bodies,
            )
        }
        nodes = tuple(
            node for node in self._all_rows if node.note.relative_path in matched_paths
        )
        preferred = preferred_note if preferred_note is not None else self._current_note
        self._set_rows(nodes, preferred_note=preferred)
        self._update_header()
        self._update_footer()

    def _set_rows(
        self, nodes: tuple[MemoryRailNode, ...], *, preferred_note: str | None
    ) -> None:
        option_list = self._note_list()
        prior_row = self._current_note_row()
        row = restore_selection_by_identity(
            nodes,
            prior_identity=preferred_note,
            prior_visual_row=prior_row,
            identity_fn=lambda node: node.identity,
        )
        generated_paths = (
            self._snapshot.generated_paths
            if self._snapshot is not None
            else frozenset()
        )
        self._rows = nodes
        self._selection_guard.clear()
        option_list.clear_options()
        option_list.add_options(
            Option(
                build_note_row_text(node, generated_paths=generated_paths),
                id=node.identity,
            )
            for node in nodes
        )
        if nodes:
            identity = nodes[row].identity
            self._selection_guard.prepare(identity, row)
            option_list.highlighted = row
            self._current_note = identity
        else:
            self._current_note = None
        self._record_session_selection()
        self._refresh_links_for_current_note()
        self._ensure_strand_read_for_current_selection()
        self._render_note_card()

    # --- selection helpers ------------------------------------------------

    def _note_list(self) -> OptionList:
        return self.query_one(f"#{_NOTE_LIST_ID}", OptionList)

    def _filter_input(self) -> Input:
        return self.query_one(f"#{_FILTER_INPUT_ID}", Input)

    def _current_note_row(self) -> int:
        option_list = self._note_list()
        if option_list.highlighted is None:
            return 0
        return max(0, min(option_list.highlighted, max(0, len(self._rows) - 1)))

    def _selected_row(self) -> MemoryRailNode | None:
        if not self._rows:
            return None
        row = self._current_note_row()
        if not 0 <= row < len(self._rows):
            return None
        return self._rows[row]

    def _selected_is_writable(self) -> bool:
        node = self._selected_row()
        snapshot = self._snapshot
        return (
            node is not None
            and not node.is_strand
            and snapshot is not None
            and node.note.relative_path not in snapshot.generated_paths
        )

    def _scope_is_unpublished(self) -> bool:
        if not getattr(self, "_ring", ()):
            return False
        scopes: set[str] = getattr(self, "_unpublished_scopes", set())
        return self._ring[self._scope_index].key in scopes

    def _mark_scope_unpublished(self, scope_key: str | None = None) -> None:
        key = scope_key
        if key is None:
            if not getattr(self, "_ring", ()):
                return
            key = self._ring[self._scope_index].key
        self._unpublished_scopes.add(key)
        if getattr(self, "is_mounted", False):
            self._update_header()
            self._update_footer()

    def _clear_scope_unpublished(self, scope_key: str) -> None:
        self._unpublished_scopes.discard(scope_key)
        if getattr(self, "is_mounted", False):
            self._update_header()
            self._update_footer()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id != _NOTE_LIST_ID:
            return
        idx = event.option_index
        if not 0 <= idx < len(self._rows):
            return
        current_idx = self._current_note_row()
        if not 0 <= current_idx < len(self._rows):
            return
        identity = self._rows[idx].identity
        current_identity = self._rows[current_idx].identity
        if self._selection_guard.should_ignore(
            identity, idx, current_identity=current_identity, current_row=current_idx
        ):
            return
        self._current_note = identity
        self._record_session_selection()
        self._refresh_links_for_current_note()
        self._ensure_strand_read_for_current_selection()
        self._update_footer()
        if self._debouncer is not None:
            self._debouncer.schedule(self._render_note_card)
        else:
            self._render_note_card()


__all__ = ["MemoryPanelStateMixin"]

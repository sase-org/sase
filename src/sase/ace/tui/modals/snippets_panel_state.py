"""Snapshot, filter, and trigger-selection state for the Snippets panel.

This is the panel's core state machine: it turns a loaded project snapshot
into the filtered, alphabetically sorted trigger list, keeps the
``OptionList`` highlight anchored to the same trigger across reloads and
filter edits, and answers "which entry is selected?" for every other mixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from sase.ace.tui.util.selection import restore_selection_by_identity
from sase.snippet.text_filter import filter_snippet_entries

from .snippets_panel_rendering import (
    build_trigger_row_text,
    canonical_snippet_trigger,
    sorted_snippet_entries,
)

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase

    from sase.ace.tui.snippets_panel_catalog import SnippetProjectSnapshot
    from sase.ace.tui.util.debounce import DetailPanelDebouncer
    from sase.ace.tui.util.selection import ProgrammaticSelectionGuard
    from sase.snippet.models import SnippetEntry
else:
    _MixinBase = object

_TRIGGER_LIST_ID = "snippets-panel-triggers"
_FILTER_INPUT_ID = "snippets-panel-filter"


class SnippetsPanelStateMixin(_MixinBase):
    """Snapshot application, filtering, and selection for :class:`SnippetsPanel`."""

    if TYPE_CHECKING:
        _all_entries: tuple[SnippetEntry, ...]
        _current_trigger: str | None
        _debouncer: DetailPanelDebouncer | None
        _entries: tuple[SnippetEntry, ...]
        _filter_bodies: bool
        _filter_text: str
        _selection_guard: ProgrammaticSelectionGuard
        _snapshot: SnippetProjectSnapshot | None

        def _refresh_relations_for_current_entry(self) -> None: ...

        def _render_snippet_card(self) -> None: ...

        def _record_session_selection(self) -> None: ...

        def _resize_trigger_rail(self) -> None: ...

        def _update_footer(self) -> None: ...

        def _update_header(self) -> None: ...

    def _apply_snapshot(
        self, snapshot: SnippetProjectSnapshot | None, *, preferred_trigger: str | None
    ) -> None:
        self._snapshot = snapshot
        catalog = snapshot.catalog if snapshot is not None else None
        self._all_entries = sorted_snippet_entries(catalog)
        preferred = canonical_snippet_trigger(catalog, preferred_trigger)
        self._resize_trigger_rail()
        self._apply_filter(
            self._filter_text,
            bodies=self._filter_bodies,
            preferred_trigger=preferred,
        )

    def _apply_filter(
        self,
        pattern: str,
        *,
        bodies: bool,
        preferred_trigger: str | None = None,
    ) -> None:
        self._filter_text = pattern
        self._filter_bodies = bodies
        entries = filter_snippet_entries(
            self._all_entries,
            pattern=pattern or None,
            include_bodies=bodies,
        )
        preferred = (
            preferred_trigger
            if preferred_trigger is not None
            else self._current_trigger
        )
        self._set_entries(entries, preferred_trigger=preferred)
        self._update_header()
        self._update_footer()

    def _set_entries(
        self, entries: tuple[SnippetEntry, ...], *, preferred_trigger: str | None
    ) -> None:
        option_list = self._trigger_list()
        prior_row = self._current_trigger_row()
        row = restore_selection_by_identity(
            entries,
            prior_identity=preferred_trigger,
            prior_visual_row=prior_row,
            identity_fn=lambda entry: entry.trigger,
        )
        self._entries = entries
        self._selection_guard.clear()
        option_list.clear_options()
        option_list.add_options(
            Option(build_trigger_row_text(entry), id=entry.trigger) for entry in entries
        )
        if entries:
            identity = entries[row].trigger
            self._selection_guard.prepare(identity, row)
            option_list.highlighted = row
            self._current_trigger = identity
        else:
            self._current_trigger = None
        self._refresh_relations_for_current_entry()
        self._record_session_selection()
        self._render_snippet_card()

    def _trigger_list(self) -> OptionList:
        return self.query_one(f"#{_TRIGGER_LIST_ID}", OptionList)

    def _filter_input(self) -> Input:
        return self.query_one(f"#{_FILTER_INPUT_ID}", Input)

    def _current_trigger_row(self) -> int:
        option_list = self._trigger_list()
        if option_list.highlighted is None:
            return 0
        return max(0, min(option_list.highlighted, max(0, len(self._entries) - 1)))

    def _selected_entry(self) -> SnippetEntry | None:
        if not self._entries:
            return None
        row = self._current_trigger_row()
        if not 0 <= row < len(self._entries):
            return None
        return self._entries[row]

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_list.id != _TRIGGER_LIST_ID:
            return
        idx = event.option_index
        if not 0 <= idx < len(self._entries):
            return
        current_idx = self._current_trigger_row()
        if not 0 <= current_idx < len(self._entries):
            return
        identity = self._entries[idx].trigger
        current_identity = self._entries[current_idx].trigger
        if self._selection_guard.should_ignore(
            identity, idx, current_identity=current_identity, current_row=current_idx
        ):
            return
        self._current_trigger = identity
        self._refresh_relations_for_current_entry()
        self._record_session_selection()
        self._update_footer()
        if self._debouncer is not None:
            self._debouncer.schedule(self._render_snippet_card)
        else:
            self._render_snippet_card()


__all__ = ["SnippetsPanelStateMixin"]

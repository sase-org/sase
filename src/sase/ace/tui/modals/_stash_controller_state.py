"""Stash controller state and lifecycle.

Private home of the shared stash state base: entry sorting, staged
restore/pin/delete marks, and authoritative store repaints. Interaction,
layout, and confirm logic lives on
:class:`sase.ace.tui.modals.stash_controller.StashControllerMixin`, which
extends the state mixin defined here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Label, OptionList

from sase.ace.tui.prompt_stash_entries import entry_prompt_segments
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.core.prompt_stash_wire import PromptStashEntryWire
from sase.project_display_names import ProjectDisplaySnapshot

from ._prompt_stash_preview import PromptStashPreviewPane
from ._stash_trash_commit import TrashCommitPreview, preview_trash_commit
from .prompt_stash_row import DEFAULT_STASH_PREVIEW_WIDTH
from .stash_messages import newest_first_stash_entries

if TYPE_CHECKING:
    from .stash_messages import StashRestoreResult


class StashControllerStateMixin:
    """Shared stash list/preview state and lifecycle.

    Hosts (the standalone modal and the overlay pane) provide ``_emit_result``
    and compose the shared pieces. ``_option_list_id`` must name the stash
    ``OptionList`` DOM id on the host.
    """

    if TYPE_CHECKING:
        _entries: list[PromptStashEntryWire]

        def _emit_result(self, result: StashRestoreResult | None = None) -> None: ...

        def _highlighted_entry(self) -> PromptStashEntryWire | None: ...

        def _highlighted_index_and_entry(
            self,
        ) -> tuple[int, PromptStashEntryWire] | None: ...

        def _paint_preview(self, entry_id: str) -> None: ...

        def _refresh_rows(self) -> None: ...

        def _title_text(self) -> str: ...

    _option_list_id = "stashed-prompts-list"

    # When True, delete marks mean Trash (the tabbed overlay): confirms
    # produce ``trash_ids`` / ``TrashRequested`` and the panel waits for an
    # authoritative repaint instead of deleting optimistically. The
    # standalone picker keeps permanent ``delete_ids``.
    _delete_marks_mean_trash = False

    def _init_stash_controller(
        self,
        entries: list[PromptStashEntryWire],
        *,
        project_display_snapshot: ProjectDisplaySnapshot | None = None,
        trash_limit: int = 100,
        trash_count: int = 0,
    ) -> None:
        # Newest first; ISO timestamps sort lexicographically, ties broken by
        # pane order so a "stash all" group keeps a stable display order.
        self._entries: list[PromptStashEntryWire] = newest_first_stash_entries(
            list(entries)
        )
        self._project_display_snapshot = (
            project_display_snapshot or ProjectDisplaySnapshot()
        )
        self._prompt_counts = {
            entry.id: len(entry_prompt_segments(entry)) for entry in self._entries
        }
        self._pop: set[str] = set()
        self._pinned: set[str] = {entry.id for entry in self._entries if entry.pinned}
        self._deleted: set[str] = set()
        # Trash-flow configuration (only the overlay changes the defaults):
        # with a zero limit there is no recovery, so delete marks stay
        # permanent even in trash mode.
        self._trash_limit = trash_limit
        self._trash_count = trash_count
        self._highlight_cache: dict[str, Text] = {}
        self._preview_debouncer: DetailPanelDebouncer | None = None
        self._refreshing_options = False
        self._narrow = True
        self._last_preview_width_budget = DEFAULT_STASH_PREVIEW_WIDTH

    def _trash_mode(self) -> bool:
        """Return True when delete marks mean Trash (overlay, limit > 0)."""
        return bool(self._delete_marks_mean_trash) and self._trash_limit > 0

    def _placeholder_text(self) -> str | None:
        """Return placeholder text for an empty list, if the host has any."""
        return None

    def _show_placeholder(self) -> None:
        try:
            pane = self.query_one(PromptStashPreviewPane)  # type: ignore[attr-defined]
        except Exception:
            return
        text = self._placeholder_text()
        if text is None:
            pane.show_placeholder()
        else:
            pane.show_placeholder(text)

    def apply_lifecycle_snapshot(
        self,
        entries: list[PromptStashEntryWire],
        *,
        trash_count: int | None = None,
    ) -> None:
        """Repaint the pane from an authoritative store snapshot.

        Staged marks for IDs absent from the snapshot are dropped (unknown
        IDs are no-ops); surviving marks are kept so a failed write leaves
        the visible rows and marks truthful. Pin state follows the snapshot.
        """
        highlighted_id: str | None = None
        highlighted = self._highlighted_index_and_entry()
        if highlighted is not None:
            highlighted_id = highlighted[1].id
        self._entries = newest_first_stash_entries(list(entries))
        live = {entry.id for entry in self._entries}
        self._pop.intersection_update(live)
        self._deleted.intersection_update(live)
        self._pinned = {entry.id for entry in self._entries if entry.pinned}
        self._prompt_counts = {
            entry.id: len(entry_prompt_segments(entry)) for entry in self._entries
        }
        for cached_id in list(self._highlight_cache):
            if cached_id not in live:
                del self._highlight_cache[cached_id]
        if trash_count is not None:
            self._trash_count = trash_count
        try:
            self.query_one("#stashed-prompts-title", Label).update(self._title_text())  # type: ignore[attr-defined]
        except Exception:
            pass
        self._refresh_rows()
        self._repaint_highlight(highlighted_id)

    def apply_store_failure(self) -> None:
        """Repaint truthfully after a failed write, keeping rows and marks."""
        self._refresh_rows()
        entry = self._highlighted_entry()
        if entry is not None:
            self._paint_preview(entry.id)
        else:
            self._show_placeholder()

    def _repaint_highlight(self, highlighted_id: str | None) -> None:
        if not self._entries:
            self._show_placeholder()
            return
        new_index: int | None = None
        if highlighted_id is not None:
            for idx, entry in enumerate(self._entries):
                if entry.id == highlighted_id:
                    new_index = idx
                    break
        if new_index is None:
            new_index = 0
        try:
            option_list = self.query_one("#stashed-prompts-list", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return
        option_list.highlighted = new_index
        self._paint_preview(self._entries[new_index].id)

    def trash_preview_for_marks(self) -> TrashCommitPreview:
        """Return the Trash confirmation preview for the current marks."""
        marked = [e.id for e in self._entries if e.id in self._deleted]
        return preview_trash_commit(
            marked,
            self._entries,
            trash_count=self._trash_count,
            trash_limit=self._trash_limit,
        )

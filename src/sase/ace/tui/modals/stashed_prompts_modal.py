"""Unified picker for stashed prompt drafts.

Lists stashed prompts newest-first with numbered restore keycaps, a relative
age, an originating-project chip, bundle marker, persistent pin marker, and a
one-line preview. ``1``-``9`` restore rows 1-9, ``0`` restores row 10, ``space``
toggles any row's pin and posts an intent message for the app layer to persist
immediately, ``tab`` marks it to restore, ``d`` marks any row for deletion, and
``enter`` confirms. Pinned rows are restored while staying stashed; unpinned
rows are restored and popped. The modal never touches the store directly;
restore/delete decisions are returned as :class:`StashRestoreResult`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.xprompt_syntax import highlight_prompt_text
from sase.ace.tui.prompt_stash_entries import entry_prompt_segments
from sase.core.prompt_stash_wire import PromptStashEntryWire

from ._prompt_stash_preview import PromptStashPreviewPane
from .base import OptionListNavigationMixin
from .prompt_stash_row import (
    DEFAULT_STASH_PREVIEW_WIDTH,
    INDEX_KEYS,
    PIN_GLYPH,
    append_shortcut,
    prompt_stash_preview_width_for_list_content,
    stash_row_age,
    stash_row_label,
)

_SPLIT_PANE_MIN_TERMINAL_WIDTH = 110


@dataclass
class StashRestoreResult:
    """Outcome of the unified stash picker.

    ``pop_ids`` are loaded into the bar and removed from the stash; ``keep_ids``
    are loaded while staying stashed; ``delete_ids`` are removed without
    loading. Entries in none of these sets stay untouched. Order is irrelevant —
    the app re-sorts loaded entries by creation time before restoring them as
    panes.
    """

    pop_ids: list[str] = field(default_factory=list)
    keep_ids: list[str] = field(default_factory=list)
    delete_ids: list[str] = field(default_factory=list)


class StashedPromptsModal(
    OptionListNavigationMixin, ModalScreen["StashRestoreResult | None"]
):
    """Multi-select picker for pinning, restoring, and deleting stashed prompts."""

    class PinToggled(Message):
        """Posted when ``space`` toggles an entry's desired persisted pin state."""

        def __init__(self, entry: PromptStashEntryWire, pinned: bool) -> None:
            super().__init__()
            self.entry = entry
            self.pinned = pinned

    _option_list_id = "stashed-prompts-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("tab", "toggle_pop", "Restore", priority=True),
        ("space", "toggle_pin", "Pin"),
        ("a", "toggle_all", "All"),
        ("d", "mark_delete", "Delete"),
        Binding("ctrl+d", "scroll_preview_down", "Preview Down", priority=True),
        Binding("ctrl+u", "scroll_preview_up", "Preview Up", priority=True),
        *[
            Binding(key, f"restore_index({idx})", f"Restore #{idx + 1}", show=False)
            for idx, key in enumerate(INDEX_KEYS)
        ],
    ]

    def __init__(self, entries: list[PromptStashEntryWire]) -> None:
        super().__init__()
        # Newest first; ISO timestamps sort lexicographically, ties broken by
        # pane order so a "stash all" group keeps a stable display order.
        self._entries: list[PromptStashEntryWire] = sorted(
            entries,
            key=lambda e: (e.created_at, e.pane_index),
            reverse=True,
        )
        self._prompt_counts = {
            entry.id: len(entry_prompt_segments(entry)) for entry in self._entries
        }
        self._pop: set[str] = set()
        self._pinned: set[str] = {entry.id for entry in self._entries if entry.pinned}
        self._deleted: set[str] = set()
        self._highlight_cache: dict[str, Text] = {}
        self._preview_debouncer: DetailPanelDebouncer | None = None
        self._refreshing_options = False
        self._narrow = True
        self._last_preview_width_budget = DEFAULT_STASH_PREVIEW_WIDTH

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="stashed-prompts-container"):
            with Horizontal(id="stashed-prompts-panels"):
                with Vertical(id="stashed-prompts-list-panel"):
                    yield Label(self._title_text(), id="stashed-prompts-title")
                    yield OptionList(*self._build_options(), id="stashed-prompts-list")
                    yield Static(self._hint_text(), id="stashed-prompts-hints")
                yield PromptStashPreviewPane(id="stashed-prompts-preview-pane")

    def on_mount(self) -> None:
        # Keep the list focused so j/k/space/tab/a/d and enter all land on it.
        self._preview_debouncer = DetailPanelDebouncer(self.app)
        self._set_narrow_mode(self.app.size.width < _SPLIT_PANE_MIN_TERMINAL_WIDTH)
        try:
            self.query_one("#stashed-prompts-list", OptionList).focus()
        except Exception:
            pass
        if self._entries:
            self._paint_preview(self._entries[0].id)
        else:
            self.query_one(PromptStashPreviewPane).show_placeholder()
        self.call_after_refresh(self._refresh_rows_for_current_width)

    def on_unmount(self) -> None:
        if self._preview_debouncer is not None:
            self._preview_debouncer.cancel()

    def on_resize(self, event: events.Resize) -> None:
        """Collapse the preview on narrow terminals and resize row snippets."""
        self._set_narrow_mode(event.size.width < _SPLIT_PANE_MIN_TERMINAL_WIDTH)
        self.call_after_refresh(self._refresh_rows_for_current_width)

    def _title_text(self) -> str:
        count = len(self._entries)
        return f"Stashed prompts ({count})"

    def _hint_text(self) -> str:
        return (
            "1-9 0 restore row · j/k navigate · enter confirm · esc/q cancel\n"
            f"space {PIN_GLYPH} pin · tab ✓ restore · d ✗ delete · a all · ^d/^u preview"
        )

    def _build_options(self, *, preview_width: int | None = None) -> list[Option]:
        if preview_width is None:
            preview_width = self._last_preview_width_budget
        self._last_preview_width_budget = preview_width
        options: list[Option] = []
        for idx, entry in enumerate(self._entries):
            label = Text(no_wrap=True, overflow="ellipsis")
            shortcut = INDEX_KEYS[idx] if idx < len(INDEX_KEYS) else None
            append_shortcut(label, shortcut)
            label.append_text(
                stash_row_label(
                    entry,
                    marked_for_pop=entry.id in self._pop,
                    marked_for_delete=entry.id in self._deleted,
                    pinned=entry.id in self._pinned,
                    age=stash_row_age(entry),
                    prompt_count=self._prompt_counts[entry.id],
                    preview_width=preview_width,
                )
            )
            options.append(Option(label, id=str(idx)))
        return options

    # -- selection state -----------------------------------------------------

    def _highlighted_index_and_entry(
        self,
    ) -> tuple[int, PromptStashEntryWire] | None:
        try:
            option_list = self.query_one("#stashed-prompts-list", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or not 0 <= highlighted < len(self._entries):
            return None
        return highlighted, self._entries[highlighted]

    def _highlighted_entry(self) -> PromptStashEntryWire | None:
        highlighted = self._highlighted_index_and_entry()
        if highlighted is None:
            return None
        return highlighted[1]

    def _refresh_rows(self) -> None:
        try:
            option_list = self.query_one("#stashed-prompts-list", OptionList)
        except Exception:
            return
        highlighted = option_list.highlighted
        self._refreshing_options = True
        try:
            option_list.clear_options()
            option_list.add_options(self._build_options())
            if self._entries and highlighted is not None:
                option_list.highlighted = min(highlighted, len(self._entries) - 1)
        finally:
            self._refreshing_options = False

    def _resolve_preview_width_budget(self) -> int:
        if self._narrow:
            return DEFAULT_STASH_PREVIEW_WIDTH
        try:
            option_list = self.query_one("#stashed-prompts-list", OptionList)
        except Exception:
            return DEFAULT_STASH_PREVIEW_WIDTH
        width = option_list.scrollable_content_region.width
        if width <= 0:
            width = option_list.content_size.width
        if width <= 0:
            width = option_list.size.width
        return prompt_stash_preview_width_for_list_content(width)

    def _refresh_rows_for_current_width(self) -> None:
        preview_width = self._resolve_preview_width_budget()
        if preview_width == self._last_preview_width_budget:
            return
        self._last_preview_width_budget = preview_width
        self._refresh_rows()

    def _set_narrow_mode(self, narrow: bool) -> None:
        self._narrow = narrow
        try:
            container = self.query_one("#stashed-prompts-container", Container)
        except Exception:
            return
        container.set_class(narrow, "-narrow")

    def _schedule_preview(self, entry_id: str) -> None:
        if self._preview_debouncer is None:
            self._paint_preview(entry_id)
            return
        self._preview_debouncer.schedule(
            lambda: self._paint_preview_if_current(entry_id)
        )

    def _paint_preview_if_current(self, entry_id: str) -> None:
        entry = self._highlighted_entry()
        if entry is not None and entry.id == entry_id:
            self._paint_preview(entry_id)

    def _paint_preview(self, entry_id: str) -> None:
        entry = next((item for item in self._entries if item.id == entry_id), None)
        if entry is None:
            self.query_one(PromptStashPreviewPane).show_placeholder()
            return
        highlighted = self._highlight_cache.get(entry.id)
        if highlighted is None:
            highlighted = highlight_prompt_text(entry.text)
            self._highlight_cache[entry.id] = highlighted
        self.query_one(PromptStashPreviewPane).show_entry(
            entry,
            prompt_count=self._prompt_counts[entry.id],
            highlighted_body=highlighted,
        )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Debounce the expensive preview paint while navigation stays instant."""
        if self._refreshing_options or event.option is None or event.option.id is None:
            return
        try:
            index = int(event.option.id)
        except ValueError:
            return
        if 0 <= index < len(self._entries):
            self._schedule_preview(self._entries[index].id)

    def action_scroll_preview_down(self) -> None:
        self.query_one(PromptStashPreviewPane).scroll_half_page(1)

    def action_scroll_preview_up(self) -> None:
        self.query_one(PromptStashPreviewPane).scroll_half_page(-1)

    def action_toggle_pop(self) -> None:
        entry = self._highlighted_entry()
        if entry is None:
            return
        if entry.id in self._pop:
            self._pop.discard(entry.id)
        else:
            self._pop.add(entry.id)
            self._deleted.discard(entry.id)
        self._refresh_rows()

    def action_toggle_pin(self) -> None:
        highlighted = self._highlighted_index_and_entry()
        if highlighted is None:
            return
        index, entry = highlighted
        pinned = entry.id not in self._pinned
        if pinned:
            self._pinned.add(entry.id)
        else:
            self._pinned.discard(entry.id)
        updated = replace(entry, pinned=pinned)
        self._entries[index] = updated
        self._refresh_rows()
        self._schedule_preview(updated.id)
        self.post_message(self.PinToggled(updated, pinned))

    def action_toggle_all(self) -> None:
        entry_ids = {entry.id for entry in self._entries}
        if not entry_ids:
            return
        if entry_ids <= self._pop:
            self._pop.difference_update(entry_ids)
        else:
            self._pop.update(entry_ids)
            self._deleted.difference_update(entry_ids)
        self._refresh_rows()

    def action_mark_delete(self) -> None:
        entry = self._highlighted_entry()
        if entry is None:
            return
        if entry.id in self._deleted:
            self._deleted.discard(entry.id)
        else:
            self._deleted.add(entry.id)
            self._pop.discard(entry.id)
        self._refresh_rows()

    def _single_restore_result(self, entry: PromptStashEntryWire) -> StashRestoreResult:
        if entry.id in self._pinned:
            return StashRestoreResult(keep_ids=[entry.id])
        return StashRestoreResult(pop_ids=[entry.id])

    def action_restore_index(self, index: int) -> None:
        if not 0 <= index < len(self._entries):
            return
        self.dismiss(self._single_restore_result(self._entries[index]))

    def action_confirm(self) -> None:
        marked = [e.id for e in self._entries if e.id in self._pop]
        pop_ids = [entry_id for entry_id in marked if entry_id not in self._pinned]
        keep_ids = [entry_id for entry_id in marked if entry_id in self._pinned]
        delete_ids = [e.id for e in self._entries if e.id in self._deleted]
        if not marked and not delete_ids:
            highlighted = self._highlighted_entry()
            if highlighted is not None:
                self.dismiss(self._single_restore_result(highlighted))
                return
            self.dismiss(None)
            return
        self.dismiss(
            StashRestoreResult(
                pop_ids=pop_ids,
                keep_ids=keep_ids,
                delete_ids=delete_ids,
            )
        )

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        # ``enter`` (and click) confirms: restore the toggled set, or just the
        # highlighted row when nothing is toggled.
        self.action_confirm()


__all__ = [
    "StashRestoreResult",
    "StashedPromptsModal",
]

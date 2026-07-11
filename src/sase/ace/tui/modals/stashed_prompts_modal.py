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
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.prompt_stash_entries import entry_prompt_segments
from sase.core.prompt_stash_wire import PromptStashEntryWire

from .base import OptionListNavigationMixin
from .prompt_stash_row import (
    INDEX_KEYS,
    PIN_GLYPH,
    append_shortcut,
    stash_row_age,
    stash_row_label,
)


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

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="stashed-prompts-container"):
            yield Label(self._title_text(), id="stashed-prompts-title")
            yield OptionList(*self._build_options(), id="stashed-prompts-list")
            yield Static(self._hint_text(), id="stashed-prompts-hints")

    def on_mount(self) -> None:
        # Keep the list focused so j/k/space/tab/a/d and enter all land on it.
        try:
            self.query_one("#stashed-prompts-list", OptionList).focus()
        except Exception:
            pass

    def _title_text(self) -> str:
        count = len(self._entries)
        return f"Stashed prompts ({count})"

    def _hint_text(self) -> str:
        return (
            "1-9 0  restore row    j/k ↑/↓ navigate    enter confirm    "
            f"esc/q cancel\nspace {PIN_GLYPH} pin    tab ✓ restore    "
            "d ✗ delete    a all"
        )

    def _build_options(self) -> list[Option]:
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
        option_list.clear_options()
        option_list.add_options(self._build_options())
        if self._entries and highlighted is not None:
            option_list.highlighted = min(highlighted, len(self._entries) - 1)

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

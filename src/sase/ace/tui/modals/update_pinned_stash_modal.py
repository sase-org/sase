"""Picker for choosing which pinned prompt stash to update."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.core.prompt_stash_wire import PromptStashEntryWire

from .base import OptionListNavigationMixin
from .prompt_stash_row import (
    INDEX_KEYS,
    append_shortcut,
    stash_row_age,
    stash_row_label,
    stash_row_prompt_count,
)


class UpdatePinnedStashModal(OptionListNavigationMixin, ModalScreen[str | None]):
    """Single-select picker for the pinned prompt stash to overwrite."""

    _option_list_id = "update-pinned-stash-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        *[
            Binding(key, f"pick_index({idx})", f"Pick #{idx + 1}", show=False)
            for idx, key in enumerate(INDEX_KEYS)
        ],
    ]

    def __init__(self, entries: list[PromptStashEntryWire]) -> None:
        super().__init__()
        self._entries: list[PromptStashEntryWire] = sorted(
            entries,
            key=lambda e: (e.created_at, e.pane_index),
            reverse=True,
        )
        self._prompt_counts = {
            entry.id: stash_row_prompt_count(entry) for entry in self._entries
        }

    def compose(self) -> ComposeResult:
        with Container(id="update-pinned-stash-container"):
            yield Label("Update pinned prompt", id="update-pinned-stash-title")
            yield OptionList(*self._build_options(), id="update-pinned-stash-list")
            yield Static(self._hint_text(), id="update-pinned-stash-hints")

    def on_mount(self) -> None:
        try:
            self.query_one("#update-pinned-stash-list", OptionList).focus()
        except Exception:
            pass

    def _hint_text(self) -> str:
        return "1-9 0  update row    j/k ↑/↓ navigate    enter confirm    esc/q cancel"

    def _build_options(self) -> list[Option]:
        options: list[Option] = []
        for idx, entry in enumerate(self._entries):
            label = Text(no_wrap=True, overflow="ellipsis")
            shortcut = INDEX_KEYS[idx] if idx < len(INDEX_KEYS) else None
            append_shortcut(label, shortcut)
            label.append_text(
                stash_row_label(
                    entry,
                    marked_for_pop=False,
                    marked_for_delete=False,
                    pinned=True,
                    age=stash_row_age(entry),
                    prompt_count=self._prompt_counts[entry.id],
                )
            )
            options.append(Option(label, id=str(idx)))
        return options

    def _highlighted_entry(self) -> PromptStashEntryWire | None:
        try:
            option_list = self.query_one("#update-pinned-stash-list", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or not 0 <= highlighted < len(self._entries):
            return None
        return self._entries[highlighted]

    def action_pick_index(self, index: int) -> None:
        if not 0 <= index < len(self._entries):
            return
        self.dismiss(self._entries[index].id)

    def action_confirm(self) -> None:
        entry = self._highlighted_entry()
        self.dismiss(entry.id if entry is not None else None)

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        self.action_confirm()


__all__ = ["UpdatePinnedStashModal"]

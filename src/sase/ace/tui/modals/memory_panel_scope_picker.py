"""Filterable scope picker for the Memory panel's ``ctrl+p`` binding.

Cycle-only navigation (``p``/``P``) is impractical once dozens of projects
are registered, so ``ctrl+p`` opens this small filterable list built from
the panel's own scope ring.
"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from .base import FilterInput, OptionListNavigationMixin
from .memory_panel_load import MemoryScopeChoice

_TITLE_ACCENT = "#FFAF5F"


class MemoryScopePicker(OptionListNavigationMixin, ModalScreen[str | None]):
    """Filterable scope picker showing each scope's display name and count."""

    _option_list_id = "memory-panel-scope-picker-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_highlighted", "Apply"),
    ]

    def __init__(
        self,
        choices: tuple[MemoryScopeChoice, ...],
        *,
        current_key: str | None = None,
    ) -> None:
        super().__init__()
        self._choices = sorted(
            choices, key=lambda choice: (choice.display_name.casefold(), choice.key)
        )
        self._filtered_choices = list(self._choices)
        self._current_key = current_key

    def compose(self) -> ComposeResult:
        with Container(id="memory-panel-scope-picker-container"):
            yield Static(self._title_text(), id="memory-panel-scope-picker-title")
            yield FilterInput(
                placeholder="Type to filter scopes…",
                id="memory-panel-scope-picker-filter",
            )
            yield OptionList(
                *self._create_options(self._filtered_choices),
                id=self._option_list_id,
            )
            yield Static(
                "Enter apply  j/k move  Esc cancel",
                id="memory-panel-scope-picker-hints",
            )

    def on_mount(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        preferred_index = 0
        if self._current_key is not None:
            for index, choice in enumerate(self._filtered_choices):
                if choice.key == self._current_key:
                    preferred_index = index
                    break
        if self._filtered_choices:
            option_list.highlighted = preferred_index
        self.query_one("#memory-panel-scope-picker-filter", FilterInput).focus()

    def _title_text(self) -> Text:
        text = Text()
        text.append("✦ ", style=f"bold {_TITLE_ACCENT}")
        text.append("Pick Memory Scope", style="bold")
        text.append("  ·  ", style="dim")
        count = len(self._filtered_choices)
        text.append(f"{count} {'scope' if count == 1 else 'scopes'}", style="dim")
        return text

    @staticmethod
    def _choice_label(choice: MemoryScopeChoice) -> Text:
        text = Text()
        text.append(f"{choice.display_name:<32.32}", style="bold")
        note_word = "note" if choice.note_count == 1 else "notes"
        text.append(f"{choice.note_count} {note_word}", style="dim")
        return text

    def _create_options(self, choices: list[MemoryScopeChoice]) -> list[Option]:
        return [Option(self._choice_label(choice), id=choice.key) for choice in choices]

    def _apply_filter(self, value: str) -> None:
        needle = value.casefold().strip()
        self._filtered_choices = [
            choice
            for choice in self._choices
            if not needle or needle in choice.display_name.casefold()
        ]
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        option_list.clear_options()
        for option in self._create_options(self._filtered_choices):
            option_list.add_option(option)
        if self._filtered_choices:
            option_list.highlighted = 0
        self.query_one("#memory-panel-scope-picker-title", Static).update(
            self._title_text()
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "memory-panel-scope-picker-filter":
            self._apply_filter(event.value)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.action_select_highlighted()

    def on_key(self, event: events.Key) -> None:
        """Keep list navigation available while the filter owns focus."""

        if event.key in ("down", "ctrl+n", "j"):
            event.prevent_default()
            event.stop()
            self.action_next_option()
        elif event.key in ("up", "ctrl+p", "k"):
            event.prevent_default()
            event.stop()
            self.action_prev_option()

    def on_option_list_option_selected(
        self,
        _event: OptionList.OptionSelected,
    ) -> None:
        self.action_select_highlighted()

    def action_select_highlighted(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return
        if 0 <= highlighted < len(self._filtered_choices):
            self.dismiss(self._filtered_choices[highlighted].key)


__all__ = ["MemoryScopePicker"]

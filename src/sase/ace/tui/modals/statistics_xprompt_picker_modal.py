"""Filterable focus picker for Statistics xprompt rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from .base import FilterInput, OptionListNavigationMixin


class _StatisticsXPromptFilterInput(FilterInput):
    """Filter input that reserves picker navigation and cancel keys."""

    async def _on_key(self, event: events.Key) -> None:
        modal = self.screen
        if isinstance(modal, StatisticsXPromptPickerModal):
            action = {
                "j": modal.action_next_option,
                "down": modal.action_next_option,
                "ctrl+n": modal.action_next_option,
                "k": modal.action_prev_option,
                "up": modal.action_prev_option,
                "ctrl+p": modal.action_prev_option,
                "escape": modal.action_cancel,
                "q": modal.action_cancel,
            }.get(event.key)
            if action is not None:
                event.prevent_default()
                event.stop()
                action()
                return
        await super()._on_key(event)


@dataclass(frozen=True)
class XPromptFocusChoice:
    """A chosen xprompt name; ``None`` means the all-xprompts scope."""

    name: str | None


class StatisticsXPromptPickerModal(
    OptionListNavigationMixin,
    ModalScreen[XPromptFocusChoice | None],
):
    """Choose one already-loaded xprompt row without performing I/O."""

    _option_list_id = "statistics-xprompt-picker-list"
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("q", "cancel", "Cancel", priority=True),
        *OptionListNavigationMixin.NAVIGATION_BINDINGS[2:],
        ("enter", "select_highlighted", "Apply"),
    ]

    def __init__(
        self,
        rows: tuple[Any, ...],
        *,
        current_focus: str | None = None,
    ) -> None:
        super().__init__()
        self._rows = rows
        self._filtered_rows = list(rows)
        self._current_focus = current_focus

    def compose(self) -> ComposeResult:
        with Container(id="statistics-xprompt-picker-container"):
            yield Static(self._title_text(), id="statistics-xprompt-picker-title")
            yield _StatisticsXPromptFilterInput(
                placeholder="Type to filter xprompts…",
                id="statistics-xprompt-picker-filter",
            )
            yield OptionList(
                *self._create_options(self._filtered_rows),
                id=self._option_list_id,
            )
            yield Static(
                "Enter focus  ·  j/k or ↑/↓ move  ·  q/Esc cancel",
                id="statistics-xprompt-picker-hints",
            )

    def on_mount(self) -> None:
        options = self.query_one(f"#{self._option_list_id}", OptionList)
        preferred_index = 0
        if self._current_focus is not None:
            for index, row in enumerate(self._filtered_rows, start=1):
                if row.name == self._current_focus:
                    preferred_index = index
                    break
        options.highlighted = preferred_index
        self.query_one(
            "#statistics-xprompt-picker-filter",
            _StatisticsXPromptFilterInput,
        ).focus()

    def _title_text(self) -> Text:
        text = Text()
        text.append("✦ ", style="bold #FF87D7")
        text.append("Focus XPrompt", style="bold")
        text.append("  ·  ", style="dim")
        text.append(f"{len(self._filtered_rows) + 1} choices", style="dim")
        return text

    @staticmethod
    def _row_label(row: Any) -> Text:
        text = Text()
        text.append(f"#{row.name:<28.28}", style="bold #87D7FF")
        kind = {"workflow": "wf", "part": "part"}.get(row.kind, row.kind)
        text.append(f"{kind:<8.8}", style="#C6A0F6")
        text.append(f"{row.runs:>5} runs", style="#5FD75F")
        if row.tags:
            text.append(f"  {', '.join(row.tags)}", style="dim italic")
        return text

    def _create_options(self, rows: list[Any]) -> list[Option]:
        all_label = Text()
        all_label.append("◆ ", style="bold #FF87D7")
        all_label.append("All xprompts", style="bold")
        options = [Option(all_label, id="all")]
        options.extend(Option(self._row_label(row), id=row.name) for row in rows)
        return options

    def _apply_filter(self, value: str) -> None:
        needle = value.strip().casefold()
        self._filtered_rows = [
            row for row in self._rows if not needle or needle in row.name.casefold()
        ]
        options = self.query_one(f"#{self._option_list_id}", OptionList)
        options.clear_options()
        for option in self._create_options(self._filtered_rows):
            options.add_option(option)
        options.highlighted = 0
        self.query_one("#statistics-xprompt-picker-title", Static).update(
            self._title_text()
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "statistics-xprompt-picker-filter":
            self._apply_filter(event.value)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.action_select_highlighted()

    def on_key(self, event: events.Key) -> None:
        """Keep list navigation available while the filter owns focus."""
        if event.key in ("escape", "q"):
            event.prevent_default()
            event.stop()
            self.action_cancel()
        elif event.key in ("down", "ctrl+n", "j"):
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
        options = self.query_one(f"#{self._option_list_id}", OptionList)
        highlighted = options.highlighted
        if highlighted is None:
            return
        if highlighted == 0:
            self.dismiss(XPromptFocusChoice(None))
            return
        index = highlighted - 1
        if 0 <= index < len(self._filtered_rows):
            self.dismiss(XPromptFocusChoice(self._filtered_rows[index].name))


__all__ = ["StatisticsXPromptPickerModal", "XPromptFocusChoice"]

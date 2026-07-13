"""Shared project-filter picker for repository and workspace inventories."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from .base import FilterInput, OptionListNavigationMixin


@dataclass(frozen=True)
class InventoryProjectChoice:
    """One project scope offered by :class:`InventoryProjectPicker`."""

    project_key: str
    display_name: str
    state: str
    repo_count: int = 0
    workspace_count: int = 0


@dataclass(frozen=True)
class InventoryProjectPickerResult:
    """A chosen project key; ``None`` means the all-projects scope."""

    project_key: str | None


class InventoryProjectPicker(
    OptionListNavigationMixin,
    ModalScreen[InventoryProjectPickerResult | None],
):
    """Filterable enabled/disabled project picker shared by inventory panes."""

    _option_list_id = "inventory-project-picker-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        ("enter", "select_highlighted", "Apply"),
    ]

    def __init__(
        self,
        choices: list[InventoryProjectChoice],
        *,
        current_project: str | None = None,
    ) -> None:
        super().__init__()
        self._choices = sorted(
            choices,
            key=lambda choice: (
                choice.state == "disabled",
                choice.display_name.casefold(),
                choice.project_key,
            ),
        )
        self._filtered_choices = list(self._choices)
        self._current_project = current_project

    def compose(self) -> ComposeResult:
        with Container(id="inventory-project-picker-container"):
            yield Static(self._title_text(), id="inventory-project-picker-title")
            yield FilterInput(
                placeholder="Type to filter projects…",
                id="inventory-project-picker-filter",
            )
            yield OptionList(
                *self._create_options(self._filtered_choices),
                id=self._option_list_id,
            )
            yield Static(
                "Enter apply  j/k move  Esc cancel",
                id="inventory-project-picker-hints",
            )

    def on_mount(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        preferred_index = 0
        if self._current_project is not None:
            for index, choice in enumerate(self._filtered_choices, start=1):
                if choice.project_key == self._current_project:
                    preferred_index = index
                    break
        option_list.highlighted = preferred_index
        self.query_one("#inventory-project-picker-filter", FilterInput).focus()

    def _title_text(self) -> Text:
        text = Text()
        text.append("✦ ", style="bold #FFAF5F")
        text.append("Filter by Project", style="bold")
        text.append("  ·  ", style="dim")
        text.append(f"{len(self._filtered_choices) + 1} choices", style="dim")
        return text

    @staticmethod
    def _choice_label(choice: InventoryProjectChoice) -> Text:
        text = Text()
        enabled = choice.state == "enabled"
        text.append(
            f"{'\u25cf' if enabled else '\u25cb'} ",
            style="bold #00D7AF" if enabled else "bold #FFD700",
        )
        text.append(f"{choice.display_name:<32.32}", style="bold")
        text.append(
            f"{choice.state:<10}",
            style="#00D7AF" if enabled else "#FFD700",
        )
        text.append(f"repos {choice.repo_count:<4}", style="dim #AF87FF")
        text.append(f"workspaces {choice.workspace_count}", style="dim #87D7FF")
        return text

    def _create_options(
        self,
        choices: list[InventoryProjectChoice],
    ) -> list[Option]:
        all_label = Text()
        all_label.append("◆ ", style="bold #FFAF5F")
        all_label.append("All projects", style="bold")
        options = [Option(all_label, id="all")]
        options.extend(
            Option(self._choice_label(choice), id=choice.project_key)
            for choice in choices
        )
        return options

    def _apply_filter(self, value: str) -> None:
        needle = value.casefold().strip()
        self._filtered_choices = [
            choice
            for choice in self._choices
            if not needle
            or needle
            in " ".join(
                (choice.display_name, choice.project_key, choice.state)
            ).casefold()
        ]
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        option_list.clear_options()
        for option in self._create_options(self._filtered_choices):
            option_list.add_option(option)
        option_list.highlighted = 0
        self.query_one("#inventory-project-picker-title", Static).update(
            self._title_text()
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "inventory-project-picker-filter":
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
        if highlighted == 0:
            self.dismiss(InventoryProjectPickerResult(None))
            return
        index = highlighted - 1
        if 0 <= index < len(self._filtered_choices):
            self.dismiss(
                InventoryProjectPickerResult(self._filtered_choices[index].project_key)
            )


__all__ = [
    "InventoryProjectChoice",
    "InventoryProjectPicker",
    "InventoryProjectPickerResult",
]

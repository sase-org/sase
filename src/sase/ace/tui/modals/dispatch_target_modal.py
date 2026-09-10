"""Prompt dispatch target picker modal."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option


LOCAL_DISPATCH_TARGET_ID = "__local__"


@dataclass(frozen=True)
class DispatchTargetChoice:
    """One prompt dispatch target row."""

    alias: str | None
    label: str
    status: str
    detail: str = ""
    enabled: bool = True

    @property
    def option_id(self) -> str:
        return self.alias or LOCAL_DISPATCH_TARGET_ID


class DispatchTargetPickerModal(ModalScreen[str | None]):
    """Pick the launch target for the active prompt pane."""

    _option_list_id = "dispatch-target-list"

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "select_highlighted", "Select"),
        ("j", "cursor_down", "Next"),
        ("k", "cursor_up", "Previous"),
        ("down", "cursor_down", "Next"),
        ("up", "cursor_up", "Previous"),
        ("ctrl+n", "cursor_down", "Next"),
        ("ctrl+p", "cursor_up", "Previous"),
    ]

    def __init__(
        self,
        choices: Iterable[DispatchTargetChoice],
        *,
        current_alias: str | None = None,
    ) -> None:
        super().__init__()
        self._choices = tuple(choices)
        self._current_id = current_alias or LOCAL_DISPATCH_TARGET_ID

    def compose(self) -> ComposeResult:
        with Container(id="dispatch-target-container"):
            yield Label("Launch Target", id="dispatch-target-title")
            yield OptionList(*self._options(), id=self._option_list_id)
            yield Static(
                "enter select  j/k move  q/esc close", id="dispatch-target-hints"
            )

    def on_mount(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        option_list.focus()
        for index, choice in enumerate(self._choices):
            if choice.option_id == self._current_id:
                option_list.highlighted = index
                break

    def on_key(self, event: events.Key) -> None:
        if event.key not in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}:
            return
        index = int(event.key)
        if index == 0:
            index = 9
        else:
            index -= 1
        if 0 <= index < len(self._choices) and self._choices[index].enabled:
            self.dismiss(self._choices[index].option_id)
            event.prevent_default()
            event.stop()

    def action_select_highlighted(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        index = option_list.highlighted
        if index is None or not 0 <= index < len(self._choices):
            return
        choice = self._choices[index]
        if choice.enabled:
            self.dismiss(choice.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option and event.option.id is not None:
            self.dismiss(str(event.option.id))

    def _options(self) -> list[Option]:
        return [
            Option(
                _choice_text(
                    index, choice, current=choice.option_id == self._current_id
                ),
                id=choice.option_id,
                disabled=not choice.enabled,
            )
            for index, choice in enumerate(self._choices)
        ]


def _choice_text(
    index: int,
    choice: DispatchTargetChoice,
    *,
    current: bool,
) -> Text:
    text = Text()
    key = "0" if index == 9 else str(index + 1)
    text.append(f"{key} ", style="dim")
    text.append(choice.label, style="bold #87D7FF" if choice.enabled else "dim")
    text.append("  ")
    status_style = "bold #87D75F"
    if not choice.enabled:
        status_style = "bold #D7AF5F"
    elif choice.status not in {"here", "ok"}:
        status_style = "#D7AF5F"
    text.append(choice.status, style=status_style)
    if current:
        text.append(" current", style="dim #87D7FF")
    if choice.detail:
        text.append("  ")
        text.append(choice.detail, style="dim")
    return text


__all__ = [
    "DispatchTargetChoice",
    "DispatchTargetPickerModal",
    "LOCAL_DISPATCH_TARGET_ID",
]

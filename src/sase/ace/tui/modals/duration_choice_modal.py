"""Reusable duration-choice modal for Ace workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static


type ChoiceValue[ResultT] = ResultT | Callable[[], ResultT]


@dataclass(frozen=True)
class DurationChoice[ResultT]:
    """One preset action in a duration-choice modal."""

    key: str
    title: str
    value: ChoiceValue[ResultT]
    subtitle: str | None = None
    tone: str = "default"


class DurationChoiceCancelled:
    """Sentinel result for cancelled duration choice flows."""


DURATION_CHOICE_CANCELLED = DurationChoiceCancelled()


type ParseDuration[ResultT] = Callable[[str], ResultT]


class DurationChoiceModal[ResultT, CancelT](ModalScreen[ResultT | CancelT]):
    """Shared popup for choosing a preset duration or entering a custom one."""

    BINDINGS = [
        *[
            Binding(str(i), f"choose('{i}')", f"Choice {i}", show=False)
            for i in range(1, 10)
        ],
        Binding("c", "open_custom", "Custom", show=False),
        Binding("escape", "cancel_or_back", "Cancel", show=False),
        Binding("q", "cancel_or_back", "Cancel", show=False),
    ]

    def __init__(
        self,
        *,
        title: str,
        choices: list[DurationChoice[ResultT]],
        parse_custom: ParseDuration[ResultT],
        custom_placeholder: str,
        cancel_result: CancelT,
        id_prefix: str = "duration-choice",
    ) -> None:
        super().__init__()
        self._title = title
        self._choices = choices
        self._choices_by_key = {choice.key: choice for choice in choices}
        self._parse_custom = parse_custom
        self._custom_placeholder = custom_placeholder
        self._id_prefix = id_prefix
        self._cancel_result = cancel_result

    def compose(self) -> ComposeResult:
        with Container(
            id=f"{self._id_prefix}-container",
            classes="duration-choice-container",
        ):
            with Vertical(
                id=f"{self._id_prefix}-body",
                classes="duration-choice-body",
            ):
                yield Label(
                    self._title,
                    id=f"{self._id_prefix}-title",
                    classes="duration-choice-title",
                )
                for choice in self._choices:
                    yield Static(
                        self._render_choice(choice),
                        classes=(
                            f"{self._id_prefix}-row duration-choice-row "
                            f"duration-choice-tone-{choice.tone}"
                        ),
                    )
                yield Static(
                    "",
                    classes=f"{self._id_prefix}-spacer duration-choice-spacer",
                )
                yield Static(
                    "  [bold]c[/]   Custom duration\n      "
                    "[dim]Enter minutes, hours, or a combined value.[/]",
                    classes=f"{self._id_prefix}-row duration-choice-row",
                )
                yield Static(
                    "",
                    classes=f"{self._id_prefix}-spacer duration-choice-spacer",
                )
                yield Static(
                    "  [bold]esc[/] Cancel",
                    classes=f"{self._id_prefix}-row duration-choice-row",
                )
                yield Input(
                    placeholder=self._custom_placeholder,
                    id=f"{self._id_prefix}-custom-input",
                    classes="hidden duration-choice-custom-input",
                    disabled=True,
                )
                yield Label(
                    "",
                    id=f"{self._id_prefix}-custom-error",
                    classes="hidden duration-choice-custom-error",
                )

    def _render_choice(self, choice: DurationChoice[ResultT]) -> str:
        line = f"  [bold]{choice.key}[/]   {choice.title}"
        if choice.subtitle:
            line = f"{line}\n      [dim]{choice.subtitle}[/]"
        return line

    def action_choose(self, key: str) -> None:
        """Dismiss with the preset value for *key*, when configured."""
        choice = self._choices_by_key.get(key)
        if choice is None:
            return
        value = choice.value
        if callable(value):
            self.dismiss(value())
            return
        self.dismiss(cast("ResultT", value))

    def action_preset_1(self) -> None:
        self.action_choose("1")

    def action_preset_2(self) -> None:
        self.action_choose("2")

    def action_preset_3(self) -> None:
        self.action_choose("3")

    def action_preset_4(self) -> None:
        self.action_choose("4")

    def action_preset_5(self) -> None:
        self.action_choose("5")

    def action_preset_6(self) -> None:
        self.action_choose("6")

    def action_preset_7(self) -> None:
        self.action_choose("7")

    def action_preset_8(self) -> None:
        self.action_choose("8")

    def action_preset_9(self) -> None:
        self.action_choose("9")

    def action_open_custom(self) -> None:
        """Reveal the custom-duration input and focus it."""
        custom_input = self.query_one(f"#{self._id_prefix}-custom-input", Input)
        custom_input.disabled = False
        custom_input.remove_class("hidden")
        custom_input.value = ""
        error = self.query_one(f"#{self._id_prefix}-custom-error", Label)
        error.update("")
        error.add_class("hidden")
        custom_input.focus()

    def action_cancel_or_back(self) -> None:
        """Esc backs out of custom input first, then cancels the modal."""
        custom_input = self.query_one(f"#{self._id_prefix}-custom-input", Input)
        if not custom_input.has_class("hidden") and custom_input.has_focus:
            custom_input.add_class("hidden")
            custom_input.disabled = True
            custom_input.value = ""
            error = self.query_one(f"#{self._id_prefix}-custom-error", Label)
            error.update("")
            error.add_class("hidden")
            return
        self.dismiss(self._cancel_result)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != f"{self._id_prefix}-custom-input":
            return
        raw = event.input.value.strip()
        error = self.query_one(f"#{self._id_prefix}-custom-error", Label)
        try:
            value = self._parse_custom(raw)
        except ValueError as exc:
            error.update(str(exc))
            error.remove_class("hidden")
            event.input.focus()
            return
        self.dismiss(value)

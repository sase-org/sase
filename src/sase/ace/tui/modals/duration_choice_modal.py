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


@dataclass(frozen=True)
class DurationAnnotation[ResultT]:
    """One free-text field folded into whichever duration the user picks.

    A duration is sometimes only half the answer -- a snoozed bead also wants
    to record *why* it was deferred. The field is always visible and never
    focused on mount, so the numbered presets stay one keystroke away, and
    every exit path (preset, callable preset, or custom duration) folds the
    text in through ``apply`` rather than each subclass remembering to.
    """

    label: str
    placeholder: str
    apply: Callable[[ResultT, str], ResultT]


class DurationChoiceCancelled:
    """Sentinel result for cancelled duration choice flows."""


DURATION_CHOICE_CANCELLED = DurationChoiceCancelled()


type ParseDuration[ResultT] = Callable[[str], ResultT]


class DurationChoiceModal[ResultT, CancelT](ModalScreen[ResultT | CancelT]):
    """Shared popup for choosing a preset duration or entering a custom one."""

    # The numbered presets are the point of this modal, so nothing may steal
    # the keyboard on mount. An annotation field is focusable and would
    # otherwise auto-focus and swallow every preset digit. Empty rather than
    # ``None``: Textual reads ``None`` as "defer to the app's AUTO_FOCUS".
    AUTO_FOCUS = ""

    BINDINGS = [
        *[
            Binding(str(i), f"choose('{i}')", f"Choice {i}", show=False)
            for i in range(1, 10)
        ],
        Binding("t", "choose('t')", "Until time", show=False),
        Binding("x", "choose('x')", "Extra choice", show=False),
        Binding("c", "open_custom", "Custom", show=False),
        Binding("r", "focus_annotation", "Annotate", show=False),
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
        annotation: DurationAnnotation[ResultT] | None = None,
    ) -> None:
        super().__init__()
        self._title = title
        self._choices = choices
        self._choices_by_key = {choice.key: choice for choice in choices}
        self._parse_custom = parse_custom
        self._custom_placeholder = custom_placeholder
        self._id_prefix = id_prefix
        self._cancel_result = cancel_result
        self._annotation = annotation

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
                if self._annotation is not None:
                    yield Static(
                        f"  [bold]r[/]   {self._annotation.label}",
                        classes=f"{self._id_prefix}-row duration-choice-row",
                    )
                    yield Input(
                        placeholder=self._annotation.placeholder,
                        id=f"{self._id_prefix}-annotation-input",
                        classes="duration-choice-annotation-input",
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
            self._dismiss_annotated(value())
            return
        self._dismiss_annotated(cast("ResultT", value))

    def _dismiss_annotated(self, value: ResultT) -> None:
        """Fold the annotation field into *value* and dismiss with it."""
        annotation = self._annotation
        if annotation is not None:
            text = self.query_one(
                f"#{self._id_prefix}-annotation-input", Input
            ).value.strip()
            value = annotation.apply(value, text)
        self.dismiss(value)

    def action_focus_annotation(self) -> None:
        """Focus the annotation field, when this modal has one."""
        if self._annotation is None:
            return
        self.query_one(f"#{self._id_prefix}-annotation-input", Input).focus()

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
        """Esc backs out of a focused input first, then cancels the modal."""
        if self._annotation is not None:
            annotation_input = self.query_one(
                f"#{self._id_prefix}-annotation-input", Input
            )
            if annotation_input.has_focus:
                # Blur rather than clear: the typed text survives so the user
                # can press a preset key, which is the whole point of leaving
                # the field.
                self.set_focus(None)
                return
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
        if event.input.id == f"{self._id_prefix}-annotation-input":
            # The annotation is never an answer on its own; submitting it just
            # hands the keyboard back to the preset keys.
            self.set_focus(None)
            return
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
        self._dismiss_annotated(value)

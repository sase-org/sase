"""Focused authored-phase threshold editor for Launch Control."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from sase.bead.config import DEFAULT_BIG_EPIC_PHASE_THRESHOLD

from .models_panel_positive_int import parse_positive_base10
from .models_panel_rendering import format_phase_threshold


def _parse_big_epic_phase_threshold(raw: str) -> int:
    """Parse one unadorned base-10 positive authored-phase threshold."""
    return parse_positive_base10(
        raw,
        empty="Enter an authored phase count.",
        minimum="The big-epic threshold must be at least 1.",
    )


class BigEpicPhaseThresholdValueModal(ModalScreen[int | None]):
    """Focused positive-integer editor for the persistent big-epic threshold."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, *, initial: int) -> None:
        super().__init__()
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Container(id="big-epic-threshold-value-container"):
            yield Static("Big Epic Threshold", id="big-epic-threshold-value-title")
            yield Static(
                self._subtitle_text(),
                id="big-epic-threshold-value-subtitle",
            )
            yield Input(
                value=str(self._initial),
                id="big-epic-threshold-value-input",
            )
            yield Label("", id="big-epic-threshold-value-error")
            yield Static(
                f"minimum 1 · package default {DEFAULT_BIG_EPIC_PHASE_THRESHOLD}",
                id="big-epic-threshold-value-constraints",
            )
            yield Static(
                "enter: preview   esc: cancel",
                id="big-epic-threshold-value-footer",
            )

    def _subtitle_text(self) -> Text:
        text = Text()
        text.append(
            "Authored phase count where an epic becomes big.",
            style="dim",
        )
        text.append("\nCurrent: ", style="dim")
        text.append(format_phase_threshold(self._initial), style="bold cyan")
        return text

    def on_mount(self) -> None:
        value_input = self.query_one("#big-epic-threshold-value-input", Input)
        value_input.focus()
        value_input.select_all()
        self._render_validation(value_input.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "big-epic-threshold-value-input":
            self._render_validation(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "big-epic-threshold-value-input":
            return
        try:
            value = _parse_big_epic_phase_threshold(event.value)
        except ValueError as error:
            self.query_one("#big-epic-threshold-value-error", Label).update(str(error))
            event.input.focus()
            return
        self.dismiss(value)

    def _render_validation(self, raw: str) -> None:
        error_label = self.query_one("#big-epic-threshold-value-error", Label)
        try:
            value = _parse_big_epic_phase_threshold(raw)
        except ValueError as error:
            error_label.update(str(error))
        else:
            error_label.update(f"valid threshold · {format_phase_threshold(value)}")

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "BigEpicPhaseThresholdValueModal",
    "_parse_big_epic_phase_threshold",
]

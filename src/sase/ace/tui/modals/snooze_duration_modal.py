"""Snooze duration picker modal for the notification panel."""

from __future__ import annotations

from datetime import datetime, timedelta

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from sase.core.time import get_timezone
from sase.xprompt._directive_time import parse_duration


_PRESET_DELTAS: dict[str, timedelta] = {
    "1": timedelta(minutes=15),
    "2": timedelta(hours=1),
    "3": timedelta(hours=4),
}


def _tomorrow_morning(now: datetime | None = None) -> datetime:
    """Compute the next 09:00 local time strictly more than a day away.

    If now is at or before 09:00 on day D, returns 09:00 on D+1.
    If now is after 09:00 on day D, also returns 09:00 on D+1.
    """
    tz = get_timezone()
    if now is None:
        now = datetime.now(tz)
    target = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return target


class SnoozeDurationModal(ModalScreen["timedelta | datetime | None"]):
    """Quick picker for choosing a snooze duration.

    Returns a ``timedelta`` for relative presets, a ``datetime`` for
    absolute presets (``"Tomorrow morning"``), or ``None`` on cancel.
    """

    BINDINGS = [
        ("1", "preset_1", "15 minutes"),
        ("2", "preset_2", "1 hour"),
        ("3", "preset_3", "4 hours"),
        ("4", "preset_4", "Tomorrow morning"),
        ("c", "open_custom", "Custom"),
        ("escape", "cancel_or_back", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="snooze-container"):
            with Vertical(id="snooze-body"):
                yield Label("Snooze", id="snooze-title")
                yield Static("  1   15 minutes", classes="snooze-row")
                yield Static("  2   1 hour", classes="snooze-row")
                yield Static("  3   4 hours", classes="snooze-row")
                yield Static("  4   Tomorrow morning", classes="snooze-row")
                yield Static("", classes="snooze-spacer")
                yield Static("  c   Custom…", classes="snooze-row")
                yield Static("", classes="snooze-spacer")
                yield Static("  esc  cancel", classes="snooze-row")
                yield Input(
                    placeholder="e.g., 30m, 2h, 1h30m",
                    id="snooze-custom-input",
                    classes="hidden",
                    disabled=True,
                )
                yield Label("", id="snooze-custom-error", classes="hidden")

    def action_preset_1(self) -> None:
        self.dismiss(_PRESET_DELTAS["1"])

    def action_preset_2(self) -> None:
        self.dismiss(_PRESET_DELTAS["2"])

    def action_preset_3(self) -> None:
        self.dismiss(_PRESET_DELTAS["3"])

    def action_preset_4(self) -> None:
        self.dismiss(_tomorrow_morning())

    def action_open_custom(self) -> None:
        """Reveal the custom-duration input and focus it."""
        custom_input = self.query_one("#snooze-custom-input", Input)
        custom_input.disabled = False
        custom_input.remove_class("hidden")
        custom_input.value = ""
        custom_input.focus()

    def action_cancel_or_back(self) -> None:
        """Esc cancels — from custom input it backs out to preset list."""
        custom_input = self.query_one("#snooze-custom-input", Input)
        if not custom_input.has_class("hidden") and custom_input.has_focus:
            custom_input.add_class("hidden")
            custom_input.disabled = True
            custom_input.value = ""
            error = self.query_one("#snooze-custom-error", Label)
            error.update("")
            error.add_class("hidden")
            return
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "snooze-custom-input":
            return
        raw = event.input.value.strip()
        seconds = parse_duration(raw)
        error = self.query_one("#snooze-custom-error", Label)
        if seconds is None or seconds <= 0:
            error.update("Invalid duration — try '30m', '2h', '1h30m'.")
            error.remove_class("hidden")
            event.input.focus()
            return
        self.dismiss(timedelta(seconds=seconds))

"""Quit / restart options modal."""

from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

type QuitOption = Literal["quit_stop_axe", "restart_tui", "restart_tui_and_axe"]


class QuitOptionsModal(ModalScreen[QuitOption | None]):
    """Single-key chooser for leaving the current ACE TUI session."""

    BINDINGS = [
        Binding("1", "choose_quit_stop_axe", "Quit & Stop axe", show=False),
        Binding("s", "choose_quit_stop_axe", "Quit & Stop axe", show=False),
        Binding("2", "choose_restart_tui", "Restart TUI", show=False),
        Binding("r", "choose_restart_tui", "Restart TUI", show=False),
        Binding(
            "3",
            "choose_restart_tui_and_axe",
            "Restart TUI & axe",
            show=False,
        ),
        Binding(
            "a",
            "choose_restart_tui_and_axe",
            "Restart TUI & axe",
            show=False,
        ),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(self, *, running_task_count: int = 0) -> None:
        super().__init__()
        self._running_task_count = max(0, running_task_count)

    def compose(self) -> ComposeResult:
        with Container(
            id="quit-options-container",
            classes="duration-choice-container",
        ):
            with Vertical(
                id="quit-options-body",
                classes="duration-choice-body",
            ):
                yield Label(
                    "Quit ACE",
                    id="quit-options-title",
                    classes="duration-choice-title",
                )
                yield Static(
                    self._render_choice(
                        "1",
                        "s",
                        "Quit & Stop axe",
                        "Stop the axe daemon and exit.",
                    ),
                    classes=(
                        "quit-options-row duration-choice-row "
                        "duration-choice-tone-primary"
                    ),
                )
                yield Static(
                    self._render_choice(
                        "2",
                        "r",
                        "Restart TUI",
                        "Reopen the TUI. Axe keeps running.",
                    ),
                    classes=(
                        "quit-options-row duration-choice-row "
                        "duration-choice-tone-primary"
                    ),
                )
                yield Static(
                    self._render_choice(
                        "3",
                        "a",
                        "Restart TUI & axe",
                        "Reopen the TUI and restart axe.",
                    ),
                    classes=(
                        "quit-options-row duration-choice-row "
                        "duration-choice-tone-accent"
                    ),
                )
                if self._running_task_count > 0:
                    yield Static(
                        self._warning_text(),
                        classes=(
                            "quit-options-warning duration-choice-row "
                            "duration-choice-tone-accent"
                        ),
                    )
                yield Static(
                    "",
                    classes="quit-options-spacer duration-choice-spacer",
                )
                yield Static(
                    "  [dim]1/s quit & stop axe · 2/r restart · "
                    "3/a restart + axe · esc cancel[/]",
                    classes="quit-options-row duration-choice-row",
                )

    @staticmethod
    def _render_choice(
        key: str,
        alternate_key: str,
        title: str,
        subtitle: str,
    ) -> str:
        return (
            f"  [bold]{key}[/]/[bold]{alternate_key}[/] "
            f" [bold]{title}[/]\n      [dim]{subtitle}[/]"
        )

    def _warning_text(self) -> str:
        noun = "proc" if self._running_task_count == 1 else "procs"
        return f"  {self._running_task_count} {noun} will be stopped."

    def action_choose_quit_stop_axe(self) -> None:
        """Quit and stop the axe daemon."""
        self.dismiss("quit_stop_axe")

    def action_choose_restart_tui(self) -> None:
        """Restart the TUI without touching axe."""
        self.dismiss("restart_tui")

    def action_choose_restart_tui_and_axe(self) -> None:
        """Restart the TUI and restart axe on startup."""
        self.dismiss("restart_tui_and_axe")

    def action_cancel(self) -> None:
        """Close without taking action."""
        self.dismiss(None)


__all__ = ["QuitOption", "QuitOptionsModal"]

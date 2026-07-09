"""Prompt-stack submit choice modal."""

from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

type PromptSubmitChoice = Literal["all", "current"]


class PromptSubmitChoiceModal(ModalScreen[PromptSubmitChoice | None]):
    """Single-key chooser for ambiguous prompt-stack submit intent."""

    BINDINGS = [
        Binding("a", "choose_all", "Submit all", show=False),
        Binding("ctrl+s", "choose_all", "Submit all", show=False),
        Binding("c", "choose_current", "Submit current", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(self, *, prompt_count: int) -> None:
        super().__init__()
        self._prompt_count = max(0, prompt_count)

    def compose(self) -> ComposeResult:
        with Container(
            id="prompt-submit-choice-container",
            classes="duration-choice-container",
        ):
            with Vertical(
                id="prompt-submit-choice-body",
                classes="duration-choice-body",
            ):
                yield Label(
                    "Submit prompt stack",
                    id="prompt-submit-choice-title",
                    classes="duration-choice-title",
                )
                yield Static(
                    self._render_choice(
                        "a",
                        "Submit all",
                        self._all_subtitle(),
                    ),
                    classes=(
                        "prompt-submit-choice-row duration-choice-row "
                        "duration-choice-tone-primary"
                    ),
                )
                yield Static(
                    self._render_choice(
                        "c",
                        "Submit current",
                        "Launch only the selected prompt as a single agent.",
                    ),
                    classes="prompt-submit-choice-row duration-choice-row",
                )
                yield Static(
                    "",
                    classes="prompt-submit-choice-spacer duration-choice-spacer",
                )
                yield Static(
                    "  [dim]a/^S all · c current · esc cancel[/]",
                    classes="prompt-submit-choice-row duration-choice-row",
                )

    def _all_subtitle(self) -> str:
        noun = "prompt" if self._prompt_count == 1 else "prompts"
        return f"Launch all {self._prompt_count} {noun} as one xprompt swarm."

    @staticmethod
    def _render_choice(key: str, title: str, subtitle: str) -> str:
        return f"  [bold]{key}[/]   [bold]{title}[/]\n      [dim]{subtitle}[/]"

    def action_choose_all(self) -> None:
        """Submit every non-empty pane."""
        self.dismiss("all")

    def action_choose_current(self) -> None:
        """Submit only the selected pane."""
        self.dismiss("current")

    def action_cancel(self) -> None:
        """Close without submitting."""
        self.dismiss(None)


__all__ = ["PromptSubmitChoice", "PromptSubmitChoiceModal"]

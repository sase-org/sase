"""Jump-to-definition action chooser modal."""

from __future__ import annotations

from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static
from rich.markup import escape

type JumpChoice = Literal["tmux", "editor", "load", "config"]


class JumpActionModal(ModalScreen[JumpChoice | None]):
    """Single-key chooser for jump-to-definition actions."""

    BINDINGS = [
        Binding("t", "choose_tmux", "Open in tmux", show=False),
        Binding("e", "choose_editor", "Open editor", show=False),
        Binding("l", "choose_load", "Load prompt", show=False),
        Binding("c", "choose_config", "Open declaration", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        *,
        title: str,
        kind_label: str,
        icon: str,
        source_display: str,
        choices: list[JumpChoice],
    ) -> None:
        super().__init__()
        self._title = title
        self._kind_label = kind_label
        self._icon = icon
        self._source_display = source_display
        self._choices = tuple(choices)

    def compose(self) -> ComposeResult:
        with Container(
            id="jump-action-container",
            classes="duration-choice-container",
        ):
            with Vertical(
                id="jump-action-body",
                classes="duration-choice-body",
            ):
                yield Label(
                    f"Jump to {self._kind_label}",
                    id="jump-action-title",
                    classes="duration-choice-title",
                )
                yield Static(
                    self._render_header(),
                    id="jump-action-header",
                    classes="jump-action-header duration-choice-row",
                )
                for choice in self._choices:
                    yield Static(
                        self._render_choice(choice),
                        classes=(
                            "jump-action-row duration-choice-row "
                            f"{self._choice_tone(choice)}"
                        ),
                    )
                yield Static(
                    "",
                    classes="jump-action-spacer duration-choice-spacer",
                )
                yield Static(
                    self._render_footer(),
                    classes="jump-action-footer duration-choice-row",
                )

    def _render_header(self) -> str:
        return (
            f"  [bold]{escape(self._icon)}[/] [bold]{escape(self._title)}[/]\n"
            f"      [dim]{escape(self._source_display)}[/]"
        )

    @staticmethod
    def _render_choice(choice: JumpChoice) -> str:
        if choice == "tmux":
            return "  [bold]t[/]   [bold]Open in new tmux pane[/]\n      [dim]Open the definition beside this TUI.[/]"
        if choice == "editor":
            return "  [bold]e[/]   [bold]Open in this pane[/]\n      [dim]Suspend the TUI, edit, then return here.[/]"
        if choice == "config":
            return "  [bold]c[/]   [bold]Open declaration[/]\n      [dim]Open where this is declared instead.[/]"
        return "  [bold]l[/]   [bold]Load into prompt input[/]\n      [dim]Stash this bar, then edit the xprompt here.[/]"

    @staticmethod
    def _choice_tone(choice: JumpChoice) -> str:
        return "duration-choice-tone-primary" if choice == "tmux" else ""

    def _render_footer(self) -> str:
        labels = {
            "tmux": "t pane",
            "editor": "e editor",
            "load": "l load",
            "config": "c declaration",
        }
        hints = [labels[choice] for choice in self._choices]
        hints.append("esc cancel")
        return f"  [dim]{' · '.join(hints)}[/]"

    def action_choose_tmux(self) -> None:
        """Choose the tmux-pane action when available."""
        if "tmux" in self._choices:
            self.dismiss("tmux")

    def action_choose_config(self) -> None:
        """Choose the declaration-open action when available."""
        if "config" in self._choices:
            self.dismiss("config")

    def action_choose_editor(self) -> None:
        """Choose the in-pane editor action when available."""
        if "editor" in self._choices:
            self.dismiss("editor")

    def action_choose_load(self) -> None:
        """Choose the prompt-load action when available."""
        if "load" in self._choices:
            self.dismiss("load")

    def action_cancel(self) -> None:
        """Close without jumping."""
        self.dismiss(None)


__all__ = ["JumpActionModal", "JumpChoice"]

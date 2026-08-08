"""Post-write action chooser for saved xprompt sources."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from sase.xprompt.write_targets import PostWriteActionKind, PostWriteActionOffer


class PostWriteActionsModal(ModalScreen[tuple[PostWriteActionKind, ...]]):
    """Toggle and run follow-up actions after a source file write."""

    BINDINGS = [
        Binding("enter", "run_selected", "Run selected", show=False),
        Binding("escape", "skip", "Skip", show=False),
        Binding("q", "skip", "Skip", show=False),
        Binding("c", "toggle_commit", "Toggle commit", show=False),
        Binding("a", "toggle_apply", "Toggle apply", show=False),
        Binding("m", "toggle_memory", "Toggle memory init", show=False),
        Binding("s", "toggle_skill", "Toggle skill init", show=False),
    ]

    def __init__(
        self,
        actions: tuple[PostWriteActionOffer, ...],
        *,
        subject: str,
    ) -> None:
        super().__init__()
        self.add_class("confirm-dialog")
        self._actions = actions
        self._subject = subject
        self._selected = {action.kind for action in actions if action.default_on}

    def compose(self) -> ComposeResult:
        dialog = Container(
            id="post-write-actions-container",
            classes="confirm-dialog-panel confirm-dialog--neutral",
        )
        dialog.border_title = Text.assemble(
            ("↑", Style(color="cyan", bold=True)),
            "  ",
            ("Post-write actions", Style(color="white", bold=True)),
        )
        dialog.border_subtitle = Text.assemble(
            ("enter", Style(color="cyan", bold=True)),
            " run · ",
            ("esc", Style(dim=True)),
            " skip",
        )
        with dialog:
            yield Static(
                self._message(),
                id="confirm-message",
                classes="confirm-dialog-message",
            )
            yield Static(
                self._subject,
                id="confirm-subject",
                classes="confirm-dialog-subject",
            )
            yield Static(
                self._rows_text(),
                id="post-write-actions-list",
                classes="post-write-actions-list",
            )
            with Horizontal(id="confirm-buttons", classes="confirm-dialog-buttons"):
                yield Button(
                    "Run selected (enter)",
                    id="confirm-btn",
                    variant="primary",
                )
                yield Button("Skip (esc)", id="cancel-btn", variant="default")

    def on_mount(self) -> None:
        self.query_one("#confirm-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-btn":
            self.action_run_selected()
            return
        if event.button.id == "cancel-btn":
            self.action_skip()

    def action_toggle_commit(self) -> None:
        self._toggle(PostWriteActionKind.COMMIT_PUSH)

    def action_toggle_apply(self) -> None:
        self._toggle(PostWriteActionKind.APPLY_CHEZMOI)

    def action_toggle_memory(self) -> None:
        self._toggle(PostWriteActionKind.MEMORY_INIT)

    def action_toggle_skill(self) -> None:
        self._toggle(PostWriteActionKind.SKILL_INIT)

    def action_run_selected(self) -> None:
        ordered = tuple(
            action.kind for action in self._actions if action.kind in self._selected
        )
        self.dismiss(ordered)

    def action_skip(self) -> None:
        self.dismiss(())

    def _toggle(self, kind: PostWriteActionKind) -> None:
        if not any(action.kind is kind for action in self._actions):
            return
        if kind in self._selected:
            self._selected.remove(kind)
        else:
            self._selected.add(kind)
        if self.is_mounted:
            self.query_one("#post-write-actions-list", Static).update(self._rows_text())

    def _message(self) -> str:
        if len(self._actions) == 1:
            return "Run this follow-up action?"
        return "Choose the follow-up actions to run."

    def _rows_text(self) -> Text:
        text = Text()
        for index, action in enumerate(self._actions):
            if index:
                text.append("\n")
            selected = action.kind in self._selected
            text.append("  ")
            text.append(action.key, style="bold cyan")
            text.append("   ")
            text.append(
                "[x] " if selected else "[ ] ", style="green" if selected else "dim"
            )
            text.append(action.label, style="bold")
            text.append("\n      ")
            text.append(action.subtitle, style="dim")
        return text


__all__ = ["PostWriteActionsModal"]

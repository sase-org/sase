"""Shared helpers for approve-options modal tests."""

from textual import events
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.bindings import DEFAULT_BINDINGS
from sase.ace.tui.modals.approve_options_modal import (
    ApproveOptionsEditPrompt,
    ApproveOptionsResult,
)


class ApproveOptionsApp(App[ApproveOptionsResult | ApproveOptionsEditPrompt | None]):
    """Minimal app for async modal tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class BindingsTestApp(
    App[ApproveOptionsResult | ApproveOptionsEditPrompt | None],
):
    """Test app with AceApp-like single-character bindings."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = DEFAULT_BINDINGS

    def compose(self) -> ComposeResult:
        yield from ()

    def check_action(
        self, action: str, parameters: tuple[object, ...] = ()
    ) -> bool | None:
        """Simulate AceApp where all action methods exist."""
        return True


class StackedFirstModal(ModalScreen[None]):
    """Minimal modal used as the bottom layer for stacking diagnostics."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Static("First modal placeholder")

    def action_cancel(self) -> None:
        self.dismiss(None)


class EventHandlerTestApp(
    App[ApproveOptionsResult | ApproveOptionsEditPrompt | None],
):
    """Test app with EventHandlersMixin-like on_key."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = DEFAULT_BINDINGS

    def __init__(self) -> None:
        super().__init__()
        self._custom_mode_prefixes: dict[str, str] = {}
        self.leaked_keys: list[str] = []

    def compose(self) -> ComposeResult:
        yield from ()

    def check_action(
        self, action: str, parameters: tuple[object, ...] = ()
    ) -> bool | None:
        return True

    def on_key(self, event: events.Key) -> None:
        """Mimics EventHandlersMixin.on_key and records keys that reach the app."""
        self.leaked_keys.append(event.key)
        if event.key in self._custom_mode_prefixes:
            event.prevent_default()
            event.stop()

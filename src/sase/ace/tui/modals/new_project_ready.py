"""Ready stage for the New Project wizard."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from .new_project_rendering import clean_source_text

_NOT_INITIALIZED = "⚠ Not initialized — agents can't launch here yet · i initialize"


class NewProjectReady(Vertical):
    """Success stage with launch, current-project, and show actions."""

    can_focus = True
    BINDINGS = [
        ("plus", "launch", "Launch"),
        ("equals", "launch", "Launch"),
        ("c", "make_current", "Current"),
        ("enter", "show_project", "Show"),
        ("i", "initialize", "Initialize"),
    ]

    class LaunchRequested(Message):
        """The user asked to open a prompt on the new project tag."""

    class CurrentRequested(Message):
        """The user asked to make the new project current."""

    class ShowRequested(Message):
        """The user asked to dismiss with a ``show(key)`` outcome."""

    class InitRequested(Message):
        """The user asked to retry the init hand-off."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._name = ""
        self._key = ""
        self._accent = ""
        self._needs_init = False

    def compose(self) -> ComposeResult:
        yield Static(
            "READY",
            id="new-project-ready-heading",
            classes="new-project-card-heading",
        )
        yield Static("", id="new-project-ready-name", markup=False)
        yield Static("", id="new-project-ready-key", markup=False)
        yield Static("", id="new-project-ready-init", markup=False)
        yield Static("", id="new-project-ready-actions", markup=False)

    def show_project(
        self,
        *,
        name: str,
        key: str,
        accent: str = "",
        needs_init: bool = False,
    ) -> None:
        """Paint the Ready card for the added project."""
        self._name = name
        self._key = key
        self._accent = accent
        self._needs_init = needs_init
        self.set_class(needs_init, "needs-init")
        if self.is_mounted:
            self._paint()

    def action_launch(self) -> None:
        self.post_message(self.LaunchRequested())

    def action_make_current(self) -> None:
        self.post_message(self.CurrentRequested())

    def action_show_project(self) -> None:
        self.post_message(self.ShowRequested())

    def action_initialize(self) -> None:
        if self._needs_init:
            self.post_message(self.InitRequested())

    def _paint(self) -> None:
        accent = clean_source_text(self._accent) or "#00D7AF"
        name = clean_source_text(self._name or self._key)
        self.query_one("#new-project-ready-name", Static).update(
            Text(name, style=f"bold {accent}")
        )
        key = Text()
        if self._key:
            key.append("key  ", style="dim")
            key.append(clean_source_text(self._key))
        self.query_one("#new-project-ready-key", Static).update(key)
        warning = Text()
        if self._needs_init:
            warning.append(_NOT_INITIALIZED, style="#FFAF5F")
        self.query_one("#new-project-ready-init", Static).update(warning)
        actions = Text()
        actions.append("+", style="bold")
        actions.append("  open prompt on +tag\n", style="dim")
        actions.append("c", style="bold")
        actions.append("  make this the current project\n", style="dim")
        actions.append("⏎", style="bold")
        actions.append("  show in Projects\n", style="dim")
        if self._needs_init:
            actions.append("i", style="bold")
            actions.append("  initialize\n", style="dim")
        actions.append("esc", style="bold")
        actions.append("  close", style="dim")
        self.query_one("#new-project-ready-actions", Static).update(actions)


__all__ = ["NewProjectReady"]

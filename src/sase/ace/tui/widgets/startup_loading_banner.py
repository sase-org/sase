"""Bold centered floating banner shown during TUI startup loading."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import LoadingIndicator, Static


class StartupLoadingBanner(Horizontal):
    """Bold, centered, floating 'starting up' banner shown during initial load."""

    DEFAULT_CSS = ""

    def compose(self) -> ComposeResult:
        yield LoadingIndicator(id="startup-loading-banner-spinner")
        yield Static("Starting sase ace…", id="startup-loading-banner-label")

    def hide(self) -> None:
        if not self.has_class("-hidden"):
            self.add_class("-hidden")

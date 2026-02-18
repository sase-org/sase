"""File browser modal for viewing notification file contents."""

from __future__ import annotations

import os

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.widgets.file_panel import _EXTENSION_TO_LEXER
from .base import OptionListNavigationMixin


class NotificationFileBrowser(OptionListNavigationMixin, ModalScreen[None]):
    """Modal for browsing files attached to a notification."""

    _option_list_id = "file-browser-list"
    BINDINGS = [*OptionListNavigationMixin.NAVIGATION_BINDINGS]

    def __init__(self, files: list[str]) -> None:
        """Initialize the file browser modal.

        Args:
            files: List of file paths to display.
        """
        super().__init__()
        self._files = files
        self._showing_content = False

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="file-browser-container"):
            yield Label("Files", id="file-browser-title")
            yield OptionList(
                *self._create_options(),
                id="file-browser-list",
            )
            with VerticalScroll(id="file-browser-content-scroll", classes="hidden"):
                yield Static(id="file-browser-content")
            yield Label(
                "Enter: view file  q/Esc: close",
                id="file-browser-hints",
            )

    def _create_options(self) -> list[Option]:
        """Create options from file paths."""
        return [
            Option(Text(self._shorten_path(f)), id=str(i))
            for i, f in enumerate(self._files)
        ]

    @staticmethod
    def _shorten_path(path: str) -> str:
        """Shorten a path by replacing home directory with ~."""
        from pathlib import Path

        return path.replace(str(Path.home()), "~")

    def on_mount(self) -> None:
        """Focus the option list on mount."""
        try:
            option_list = self.query_one("#file-browser-list", OptionList)
            option_list.focus()
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle file selection — show file content."""
        if event.option and event.option.id is not None:
            idx = int(event.option.id)
            if 0 <= idx < len(self._files):
                self._show_file_content(self._files[idx])

    def _show_file_content(self, file_path: str) -> None:
        """Display the contents of a file with syntax highlighting."""
        expanded_path = os.path.expanduser(file_path)

        # Update title to show current file
        title = self.query_one("#file-browser-title", Label)
        title.update(self._shorten_path(expanded_path))

        # Hide file list, show content
        self.query_one("#file-browser-list", OptionList).add_class("hidden")
        content_scroll = self.query_one("#file-browser-content-scroll")
        content_scroll.remove_class("hidden")
        self._showing_content = True

        # Update hints
        hints = self.query_one("#file-browser-hints", Label)
        hints.update("q/Esc: back to file list")

        content_widget = self.query_one("#file-browser-content", Static)

        try:
            with open(expanded_path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content_widget.update(Text("Could not read file.", style="dim italic"))
            return

        if not content.strip():
            content_widget.update(Text("File is empty.", style="dim italic"))
            return

        # Detect lexer from file extension
        _, ext = os.path.splitext(expanded_path)
        lexer = _EXTENSION_TO_LEXER.get(ext.lower(), "text")

        syntax = Syntax(
            content,
            lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        content_widget.update(syntax)

    def action_cancel(self) -> None:
        """Cancel — if showing content, go back to file list; otherwise dismiss."""
        if self._showing_content:
            self._back_to_file_list()
        else:
            self.dismiss(None)

    def _back_to_file_list(self) -> None:
        """Return to the file list view."""
        self._showing_content = False

        # Restore title
        title = self.query_one("#file-browser-title", Label)
        title.update("Files")

        # Show file list, hide content
        self.query_one("#file-browser-list", OptionList).remove_class("hidden")
        self.query_one("#file-browser-content-scroll").add_class("hidden")

        # Restore hints
        hints = self.query_one("#file-browser-hints", Label)
        hints.update("Enter: view file  q/Esc: close")

        # Re-focus file list
        try:
            self.query_one("#file-browser-list", OptionList).focus()
        except Exception:
            pass

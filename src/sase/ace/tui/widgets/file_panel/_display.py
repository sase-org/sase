"""Static file and diff display mixin for the file panel."""

import os
from datetime import datetime

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll

from ._messages import _EXTENSION_TO_LEXER


class FilePanelDisplayMixin:
    """Mixin providing static file/diff display for AgentFilePanel."""

    _full_content: str | None
    _static_header_path: str | None

    def _display_file_with_timestamp(
        self,
        diff_output: str | None,
        fetch_time: datetime,
        *,
        post_visibility_message: bool = True,
        is_stale: bool = False,
    ) -> None:
        """Display file output with fetch timestamp.

        Args:
            diff_output: The diff output or None if no changes.
            fetch_time: When the file was fetched.
            post_visibility_message: Whether to post visibility change message.
                Set to False when displaying cached data to avoid flicker.
            is_stale: Whether the content is stale (showing while refreshing).
        """
        # Track last displayed content for change detection
        self._last_file_content = diff_output

        # Post visibility message to parent (only for fresh fetches to avoid flicker)
        if post_visibility_message:
            self._post_file_visibility(has_file=diff_output is not None)  # type: ignore[attr-defined]

        # Build refresh indicator if stale and background refreshing
        refresh_indicator = ""
        if is_stale and self._is_background_refreshing:  # type: ignore[attr-defined]
            refresh_indicator = " (refreshing...)"

        if diff_output:
            # For simplicity, prepend timestamp to the diff output
            diff_with_header = (
                f"# Last fetched: {fetch_time.strftime('%H:%M:%S')}"
                f"{refresh_indicator}\n\n{diff_output}"
            )

            # Store content for future re-render
            self._full_content = diff_with_header
            self._full_content_lexer = "diff"
            self._content_mode = "diff"

            syntax = Syntax(
                diff_with_header,
                "diff",
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
            )
            self.update(syntax)  # type: ignore[attr-defined]
        else:
            text = Text()
            text.append("Last fetched: ", style="dim")
            text.append(fetch_time.strftime("%H:%M:%S"), style="#87D7FF")
            if refresh_indicator:
                text.append(refresh_indicator, style="dim italic")
            text.append("\n\n")
            text.append("No changes detected.\n", style="dim italic")
            self.update(text)  # type: ignore[attr-defined]

        self._has_displayed_content = True

    def display_static_diff(self, diff_path: str) -> None:
        """Display a static diff from a file (no auto-refresh).

        Args:
            diff_path: Path to the diff file (may use ~ for home).
        """
        expanded_path = os.path.expanduser(diff_path)
        try:
            with open(expanded_path, encoding="utf-8") as f:
                diff_content = f.read()
        except Exception:
            text = Text("Could not read diff file.\n", style="dim italic")
            self.update(text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return

        if not diff_content.strip():
            text = Text("Diff file is empty.\n", style="dim italic")
            self.update(text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return

        # Display diff with file path header
        diff_with_header = f"# Static diff (from saved file)\n\n{diff_content}"

        # Store content for future re-render
        self._full_content = diff_with_header
        self._full_content_lexer = "diff"
        self._content_mode = "static_diff"
        self._static_header_path = expanded_path

        header = Text(expanded_path, style="bold #D7AF5F underline")
        syntax = Syntax(
            diff_with_header,
            "diff",
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        self.update(Group(header, Text(""), syntax))  # type: ignore[attr-defined]

        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]

    def display_static_file(self, file_path: str) -> None:
        """Display a static file with syntax highlighting (no auto-refresh).

        Auto-detects the lexer from the file extension.

        Args:
            file_path: Path to the file (may use ~ for home).
        """
        expanded_path = os.path.expanduser(file_path)
        try:
            with open(expanded_path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            text = Text("Could not read file.\n", style="dim italic")
            self.update(text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return

        if not content.strip():
            text = Text("File is empty.\n", style="dim italic")
            self.update(text)  # type: ignore[attr-defined]
            self._post_file_visibility(has_file=False)  # type: ignore[attr-defined]
            return

        # Detect lexer from file extension
        _, ext = os.path.splitext(expanded_path)
        lexer = _EXTENSION_TO_LEXER.get(ext.lower(), "text")

        # Store content for future re-render
        self._full_content = content
        self._full_content_lexer = lexer
        self._content_mode = "static"
        self._static_header_path = expanded_path

        header = Text(expanded_path, style="bold #D7AF5F underline")
        syntax = Syntax(
            content,
            lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        self.update(Group(header, Text(""), syntax))  # type: ignore[attr-defined]

        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)  # type: ignore[attr-defined]

    def _show_loading(self) -> None:
        """Display loading indicator only if panel was previously visible."""
        if not self._has_displayed_content:
            return
        text = Text()
        text.append("Loading file...\n", style="bold #87D7FF")
        text.append("Please wait while fetching changes.", style="dim")
        self.update(text)  # type: ignore[attr-defined]

    def show_empty(self) -> None:
        """Show empty state."""
        self._reset_content_state()
        self._has_displayed_content = False
        text = Text("No agent selected", style="dim italic")
        self.update(text)  # type: ignore[attr-defined]

    def _reset_content_state(self) -> None:
        """Reset content-related fields to defaults."""
        self._full_content = None
        self._full_content_lexer = "text"
        self._content_mode = "none"
        self._static_header_path = None

    def _render_content(self) -> None:
        """Re-render full_content."""
        if self._full_content is None:
            return

        lexer = (
            "diff"
            if self._content_mode in ("diff", "static_diff")
            else self._full_content_lexer
        )
        syntax = Syntax(
            self._full_content,
            lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        if self._content_mode in ("static", "static_diff"):
            header = Text(
                self._static_header_path or "", style="bold #D7AF5F underline"
            )
            self.update(Group(header, Text(""), syntax))  # type: ignore[attr-defined]
        else:
            self.update(syntax)  # type: ignore[attr-defined]

    def _update_timestamp_header(
        self, fetch_time: datetime, *, refreshing: bool = False
    ) -> None:
        """Update the timestamp line in _full_content without re-fetching."""
        if self._full_content is None or self._content_mode != "diff":
            return
        newline_idx = self._full_content.index("\n")
        suffix = " (refreshing...)" if refreshing else ""
        new_header = f"# Last fetched: {fetch_time.strftime('%H:%M:%S')}{suffix}"
        self._full_content = new_header + self._full_content[newline_idx:]

    def _get_scroll_container(self) -> VerticalScroll | None:
        """Get the parent scroll container for this file panel.

        Returns:
            The VerticalScroll container, or None if not found.
        """
        try:
            return self.app.query_one("#agent-file-scroll", VerticalScroll)  # type: ignore[attr-defined]
        except Exception:
            return None

    def _save_scroll_position(self) -> float:
        """Save the current scroll position.

        Returns:
            The current scroll Y position, or 0 if unavailable.
        """
        container = self._get_scroll_container()
        if container is not None:
            return container.scroll_y
        return 0.0

    def _restore_scroll_position(self, position: float) -> None:
        """Restore a previously saved scroll position.

        Args:
            position: The scroll Y position to restore.
        """
        container = self._get_scroll_container()
        if container is not None:
            self.call_after_refresh(  # type: ignore[attr-defined]
                lambda: container.scroll_to(y=position, animate=False)
            )

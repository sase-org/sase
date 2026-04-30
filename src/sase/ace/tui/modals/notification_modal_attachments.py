"""Attachment preview behavior for the notification modal."""

from __future__ import annotations

import os
import subprocess
from typing import Any

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from sase.ace.hints import build_editor_args
from sase.ace.tui.graphics import (
    GraphicsCapability,
    KittyImageRenderable,
    TerminalControlRenderable,
    image_preview_size_for_viewport,
    is_supported_image_path,
)
from sase.ace.tui.widgets.file_panel import _EXTENSION_TO_LEXER
from sase.notifications import Notification


class NotificationAttachmentMixin:
    """Render notification attachments and open the current file in an editor."""

    def _display_file(self: Any, notification: Notification | None) -> None:
        """Render file content with syntax highlighting in the right pane."""
        title = self.query_one("#notification-file-title", Label)
        content_widget = self.query_one("#notification-file-content", Static)

        if notification is None or not notification.files:
            title.update("No files attached")
            cleanup = self._consume_image_cleanup_segments()
            content_widget.update(Group(*cleanup, "") if cleanup else "")
            return

        files = notification.files
        if self._current_file_index >= len(files):
            self._current_file_index = 0

        file_path = files[self._current_file_index]
        short = self._shorten_path(file_path)
        title.update(f"File {self._current_file_index + 1}/{len(files)}: {short}")

        expanded_path = os.path.expanduser(file_path)

        if is_supported_image_path(expanded_path):
            self._display_image_file(expanded_path, content_widget)
            return

        cleanup = self._consume_image_cleanup_segments()
        try:
            with open(expanded_path, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            text = Text("Could not read file.", style="dim italic")
            content_widget.update(Group(*cleanup, text) if cleanup else text)
            self._reset_file_scroll()
            return

        if not content.strip():
            text = Text("File is empty.", style="dim italic")
            content_widget.update(Group(*cleanup, text) if cleanup else text)
            self._reset_file_scroll()
            return

        _, ext = os.path.splitext(expanded_path)
        lexer = _EXTENSION_TO_LEXER.get(ext.lower(), "text")

        syntax = Syntax(
            content,
            lexer,
            theme="monokai",
            line_numbers=True,
            word_wrap=True,
        )
        content_widget.update(Group(*cleanup, syntax) if cleanup else syntax)
        self._reset_file_scroll()

    def _display_image_file(
        self: Any, expanded_path: str, content_widget: Static
    ) -> None:
        """Render an image attachment using the TUI graphics preview layer."""
        cleanup = self._consume_image_cleanup_segments()
        capability = self._graphics_capability()
        columns, rows = self._image_preview_size(content_widget)
        renderable = self._image_preview(
            expanded_path,
            capability,
            columns=columns,
            rows=rows,
        )
        self._current_image_renderable = (
            renderable if isinstance(renderable, KittyImageRenderable) else None
        )
        content_widget.update(Group(*cleanup, renderable))
        self._reset_file_scroll()

    def _image_preview_size(self: Any, content_widget: Static) -> tuple[int, int]:
        """Choose a placeholder size from the visible notification file pane."""
        try:
            scroll = self.query_one("#notification-file-scroll", VerticalScroll)
        except Exception:
            scroll = None
        return image_preview_size_for_viewport(
            scroll_widget=scroll,
            content_widget=content_widget,
        )

    def _graphics_capability(self: Any) -> GraphicsCapability:
        """Return app graphics support, or a fallback when the modal is unmounted."""
        try:
            capability = getattr(self.app, "graphics_capability", None)
        except Exception:
            capability = None
        if isinstance(capability, GraphicsCapability):
            return capability
        return GraphicsCapability.unavailable("terminal graphics were not probed")

    def _consume_image_cleanup_segments(self: Any) -> list[TerminalControlRenderable]:
        """Return terminal cleanup controls for the active Kitty image, if any."""
        current = self._current_image_renderable
        self._current_image_renderable = None
        if isinstance(current, KittyImageRenderable):
            return [TerminalControlRenderable(current.cleanup_sequence())]
        return []

    def _reset_file_scroll(self: Any) -> None:
        """Reset the file scroll pane to the top."""
        try:
            scroll = self.query_one("#notification-file-scroll", VerticalScroll)
            scroll.scroll_home(animate=False)
        except Exception:
            pass

    def action_next_file(self: Any) -> None:
        """Cycle to the next attached file."""
        notification = self._get_highlighted_notification()
        if notification and notification.files:
            self._current_file_index = (self._current_file_index + 1) % len(
                notification.files
            )
            self._display_file(notification)

    def action_prev_file(self: Any) -> None:
        """Cycle to the previous attached file."""
        notification = self._get_highlighted_notification()
        if notification and notification.files:
            self._current_file_index = (self._current_file_index - 1) % len(
                notification.files
            )
            self._display_file(notification)

    def action_scroll_file_down(self: Any) -> None:
        """Scroll the file content down by half a page."""
        scroll = self.query_one("#notification-file-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_file_up(self: Any) -> None:
        """Scroll the file content up by half a page."""
        scroll = self.query_one("#notification-file-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def action_open_in_editor(self: Any) -> None:
        """Open the currently displayed file in $EDITOR."""
        notification = self._get_highlighted_notification()
        if not notification or not notification.files:
            return

        file_path = notification.files[self._current_file_index]
        expanded = os.path.expanduser(file_path)
        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [expanded])

        with self.app.suspend():
            subprocess.run(editor_args, check=False)

        self._display_file(notification)

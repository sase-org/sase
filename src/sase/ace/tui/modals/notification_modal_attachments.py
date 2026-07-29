"""Attachment preview behavior for the notification modal."""

from __future__ import annotations

import os
import subprocess
from typing import Any

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from sase.ace.hints import build_editor_args
from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.ace.tui.graphics import (
    ImageRenderContext,
    image_render_context,
    image_preview_size_for_viewport,
    is_supported_image_path,
    is_supported_video_path,
    view_artifact_file,
)
from sase.ace.tui.widgets.file_panel import _EXTENSION_TO_LEXER
from sase.notifications import Notification

from .notification_modal_constants import notification_icon


class NotificationAttachmentMixin:
    """Render notification attachments and open the current file in an editor."""

    def _display_file(self: Any, notification: Notification | None) -> None:
        """Render file content with syntax highlighting in the right pane."""
        title = self.query_one("#notification-file-title", Label)
        content_widget = self.query_one("#notification-file-content", Static)

        if notification is not None:
            question_pane = self._render_question_pane(notification)
            if question_pane is not None:
                pane_title, pane_content = question_pane
                self._set_image_preview_mode(False)
                title.update(self._detail_title(notification, pane_title))
                cleanup = self._consume_image_cleanup_segments()
                content_widget.update(
                    Group(*cleanup, pane_content) if cleanup else pane_content
                )
                self._reset_file_scroll()
                return

            report_pane = self._render_report_pane(notification)
            if report_pane is not None:
                pane_title, pane_content = report_pane
                self._set_image_preview_mode(False)
                title.update(self._detail_title(notification, pane_title))
                cleanup = self._consume_image_cleanup_segments()
                content_widget.update(
                    Group(*cleanup, pane_content) if cleanup else pane_content
                )
                self._reset_file_scroll()
                return

        if notification is None or not notification.files:
            self._set_image_preview_mode(False)
            title.update(
                "No files attached"
                if notification is None
                else self._detail_title(notification, "No files attached")
            )
            cleanup = self._consume_image_cleanup_segments()
            content_widget.update(Group(*cleanup, "") if cleanup else "")
            return

        files = notification.files
        if self._current_file_index >= len(files):
            self._current_file_index = 0

        file_path = files[self._current_file_index]
        short = self._shorten_path(file_path)
        title.update(
            self._detail_title(
                notification,
                f"File {self._current_file_index + 1}/{len(files)}: {short}",
            )
        )

        expanded_path = os.path.expanduser(file_path)

        if is_supported_image_path(expanded_path):
            self._set_image_preview_mode(True)
            self._display_image_file(expanded_path, content_widget)
            return
        if is_supported_video_path(expanded_path):
            self._set_image_preview_mode(False)
            cleanup = self._consume_image_cleanup_segments()
            text = _video_attachment_placeholder(expanded_path)
            content_widget.update(Group(*cleanup, text) if cleanup else text)
            self._reset_file_scroll()
            return

        self._set_image_preview_mode(False)
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

    @staticmethod
    def _detail_title(notification: Notification, title: str) -> str:
        """Build the icon-led header for the highlighted notification."""
        icon = notification_icon(notification.action, notification.icon)
        return f"{icon} {notification.sender} · {title}"

    def _display_image_file(
        self: Any, expanded_path: str, content_widget: Static
    ) -> None:
        """Render an image attachment using the TUI graphics preview layer."""
        cleanup = self._consume_image_cleanup_segments()
        context = self._image_render_context()
        columns, rows = self._image_preview_size(content_widget)
        renderable = self._image_preview(
            expanded_path,
            context,
            columns=columns,
            rows=rows,
        )
        content_widget.update(Group(*cleanup, renderable))
        self._reset_file_scroll()

    def _image_preview_size(self: Any, content_widget: Static) -> tuple[int, int]:
        """Choose a preview size from the visible notification file pane."""
        try:
            scroll = self.query_one("#notification-file-scroll", VerticalScroll)
        except Exception:
            scroll = None
        return image_preview_size_for_viewport(
            scroll_widget=scroll,
            content_widget=content_widget,
        )

    def _set_image_preview_mode(self: Any, enabled: bool) -> None:
        """Shift notification layout toward the preview pane for image files."""
        for selector in (
            "#notification-container",
            "#notification-left",
            "#notification-right",
        ):
            try:
                widget = self.query_one(selector)
            except Exception:
                continue
            if enabled:
                widget.add_class("image-preview")
            else:
                widget.remove_class("image-preview")

    def _image_render_context(self: Any) -> ImageRenderContext:
        """Return the image preview rendering context."""
        return image_render_context()

    def _consume_image_cleanup_segments(self: Any) -> list[RenderableType]:
        """Compatibility no-op for surfaces that used image cleanup state."""
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

    def action_copy_file_path(self: Any) -> None:
        """Copy the currently displayed attachment path to the clipboard."""
        notification = self._get_highlighted_notification()
        if not notification or not notification.files:
            self.notify("No file path to copy", severity="warning")
            return

        if self._current_file_index >= len(notification.files):
            self._current_file_index = 0

        path = self._shorten_path(notification.files[self._current_file_index])
        schedule_copy_delivery(
            self,
            path,
            copied_label=f"attachment path ({path})",
            task_name="sase-copy-notification-attachment-path",
        )

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

    def _get_current_image_path(self: Any) -> str | None:
        """Return the highlighted notification's current image attachment."""
        artifact_path = self._get_current_viewable_artifact_path()
        if artifact_path is None or not is_supported_image_path(artifact_path):
            return None
        return artifact_path

    def _get_current_viewable_artifact_path(self: Any) -> str | None:
        """Return the highlighted notification's current viewable attachment."""
        notification = self._get_highlighted_notification()
        if not notification or not notification.files:
            return None
        if self._current_file_index >= len(notification.files):
            self._current_file_index = 0
        file_path = notification.files[self._current_file_index]
        expanded = os.path.expanduser(file_path)
        if not (is_supported_image_path(expanded) or is_supported_video_path(expanded)):
            return None
        if not os.path.exists(expanded):
            return None
        return expanded

    def action_view_image(self: Any) -> None:
        """Open the currently displayed media attachment with the artifact viewer."""
        artifact_path = self._get_current_viewable_artifact_path()
        if artifact_path is None:
            self.notify("No image or video visible", severity="warning")
            return

        with self.app.suspend():
            result = view_artifact_file(artifact_path)
        if result.warning is not None:
            self.notify(result.warning, severity="warning")


def _video_attachment_placeholder(expanded_path: str) -> Text:
    """Return a styled inline placeholder for a video attachment."""
    name = os.path.basename(expanded_path) or expanded_path
    text = Text()
    text.append("▶ video", style="bold #D7AF5F")
    text.append("\n")
    text.append(name, style="bold #87D7FF")
    text.append("\n")
    text.append(expanded_path, style="dim")
    text.append("\n\n")
    text.append("press V to play", style="dim italic")
    return text

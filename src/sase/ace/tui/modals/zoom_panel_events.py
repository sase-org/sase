"""Message handlers for the Agents-tab zoom panel modal."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll

from ..widgets.file_panel import (
    FileLineCountChanged,
    FileListChanged,
    FileVisibilityChanged,
)
from ..widgets.tools_panel import ToolsVisibilityChanged
from .zoom_panel_types import ZoomPanelTarget


def on_file_visibility_changed(modal: Any, message: FileVisibilityChanged) -> None:
    """Track file availability inside the modal."""
    modal._has_file_content = message.has_file
    modal._update_header()
    if not message.has_file and modal._target == ZoomPanelTarget.FILE:
        modal._clear_reveal_state()
        modal._show_target(ZoomPanelTarget.METADATA)
    message.stop()


def on_file_list_changed(modal: Any, message: FileListChanged) -> None:
    """Refresh the header counter after file cycling."""
    modal._has_file_content = message.file_count > 0
    modal._update_header()
    message.stop()


def on_file_line_count_changed(modal: Any, message: FileLineCountChanged) -> None:
    """Mirror file line-count state in the modal border subtitle."""
    scroll = modal.query_one("#zoom-file-scroll", VerticalScroll)
    if message.total_lines == 0:
        scroll.border_subtitle = ""
    elif message.capped:
        scroll.border_subtitle = Text(
            f"1-{message.visible_lines} of {message.total_lines} lines (E: editor)",
            style="dim #87D7FF",
        )
    else:
        scroll.border_subtitle = Text(
            f"{message.total_lines} lines",
            style="dim #5FAFAF",
        )
    message.stop()


def on_tools_visibility_changed(modal: Any, message: ToolsVisibilityChanged) -> None:
    """Track tools availability inside the modal."""
    modal._has_tools_content = message.has_tools
    modal._update_header()
    if not message.has_tools and modal._target == ZoomPanelTarget.TOOLS:
        modal._clear_reveal_state()
        modal._show_target(ZoomPanelTarget.METADATA)
    message.stop()

"""File path completion engine and dropdown widget for the prompt input."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from textual.widgets import Static

MAX_VISIBLE = 15


@dataclass
class CompletionEntry:
    """A single file/directory completion entry."""

    name: str
    is_dir: bool


def extract_path_token(line: str, col: int) -> tuple[int, str] | None:
    """Extract a path token ending at the given column position.

    Scans backwards from *col* to the first whitespace or start of line.
    Returns ``(start_col, token)`` if the token looks like a path prefix,
    otherwise ``None``.
    """
    start = col
    while start > 0 and line[start - 1] not in (" ", "\t"):
        start -= 1

    token = line[start:col]
    if not token:
        return None

    if token.startswith(("~/", "./", "../", "/")):
        return (start, token)

    return None


def list_completions(partial_path: str, workspace_dir: str) -> list[CompletionEntry]:
    """List file/directory completions for a partial path.

    Args:
        partial_path: The partial path typed by the user (e.g. ``~/Dow``).
        workspace_dir: Directory for resolving ``./`` and ``../``.

    Returns:
        Sorted list of matching entries (directories first, then alphabetical).
    """
    # Split into directory part and filter prefix
    if partial_path.endswith("/"):
        dir_part = partial_path
        filter_prefix = ""
    elif "/" in partial_path:
        last_slash = partial_path.rfind("/")
        dir_part = partial_path[: last_slash + 1]
        filter_prefix = partial_path[last_slash + 1 :]
    else:
        return []

    # Resolve the directory
    if dir_part.startswith("~/"):
        resolved = Path.home() / dir_part[2:]
    elif dir_part.startswith("./"):
        resolved = Path(workspace_dir) / dir_part[2:]
    elif dir_part.startswith("../"):
        resolved = (Path(workspace_dir) / ".." / dir_part[3:]).resolve()
    elif dir_part.startswith("/"):
        resolved = Path(dir_part)
    else:
        return []

    try:
        resolved = resolved.resolve()
    except OSError:
        return []

    if not resolved.is_dir():
        return []

    # List and filter entries
    entries: list[CompletionEntry] = []
    show_hidden = filter_prefix.startswith(".")

    try:
        with os.scandir(resolved) as scanner:
            for entry in scanner:
                name = entry.name
                if name.startswith(".") and not show_hidden:
                    continue
                if filter_prefix and not name.lower().startswith(filter_prefix.lower()):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=True)
                except OSError:
                    is_dir = False
                entries.append(CompletionEntry(name=name, is_dir=is_dir))
    except (PermissionError, OSError):
        return []

    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries


class FileCompletionDropdown(Static):
    """Compact dropdown widget showing file path completion entries."""

    def __init__(self, entries: list[CompletionEntry], path_display: str) -> None:
        super().__init__(id="file-completion-dropdown")
        self._entries = entries
        self._path_display = path_display
        self._selected = 0
        self._scroll_offset = 0

    @property
    def selected_entry(self) -> CompletionEntry | None:
        """The currently selected completion entry."""
        if not self._entries or self._selected >= len(self._entries):
            return None
        return self._entries[self._selected]

    def dropdown_height(self) -> int:
        """Calculate the widget height in rows (content lines + border)."""
        if not self._entries:
            return 3
        visible = min(len(self._entries), MAX_VISIBLE)
        has_more = len(self._entries) > MAX_VISIBLE
        return visible + (1 if has_more else 0) + 2

    def move_down(self) -> None:
        """Move selection down, wrapping to top."""
        if not self._entries:
            return
        self._selected = (self._selected + 1) % len(self._entries)
        self._ensure_visible()
        self._render_content()

    def move_up(self) -> None:
        """Move selection up, wrapping to bottom."""
        if not self._entries:
            return
        self._selected = (self._selected - 1) % len(self._entries)
        self._ensure_visible()
        self._render_content()

    def update_entries(self, entries: list[CompletionEntry], path_display: str) -> None:
        """Replace entries and reset selection."""
        self._entries = entries
        self._path_display = path_display
        self._selected = 0
        self._scroll_offset = 0
        self._render_content()

    def _ensure_visible(self) -> None:
        """Adjust scroll offset so the selected item is visible."""
        if self._selected < self._scroll_offset:
            self._scroll_offset = self._selected
        elif self._selected >= self._scroll_offset + MAX_VISIBLE:
            self._scroll_offset = self._selected - MAX_VISIBLE + 1

    def on_mount(self) -> None:
        """Render initial content."""
        self._render_content()

    def _render_content(self) -> None:
        """Rebuild the Rich Text display from current state."""
        text = Text()
        visible = self._entries[self._scroll_offset : self._scroll_offset + MAX_VISIBLE]

        for i, entry in enumerate(visible):
            actual_idx = i + self._scroll_offset
            is_selected = actual_idx == self._selected

            if is_selected:
                text.append("▸ ", style="bold")
            else:
                text.append("  ")

            if entry.is_dir:
                text.append("📁 ")
                style = "bold cyan" if is_selected else "cyan"
                text.append(entry.name + "/", style=style)
            else:
                text.append("📄 ")
                style = "bold" if is_selected else ""
                text.append(entry.name, style=style)

            if i < len(visible) - 1:
                text.append("\n")

        remaining = len(self._entries) - self._scroll_offset - len(visible)
        if remaining > 0:
            text.append("\n")
            text.append(f"  ↓ {remaining} more...", style="dim")

        self.update(text)
        self.border_title = self._path_display

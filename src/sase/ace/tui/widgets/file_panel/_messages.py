"""Message classes, cache, and constants for the file panel."""

from dataclasses import dataclass
from datetime import datetime

from textual.message import Message

from ...models.agent import Agent


class FileVisibilityChanged(Message):
    """Message posted when file panel visibility should change."""

    def __init__(
        self,
        has_file: bool,
        file_count: int = 0,
        file_index: int = 0,
    ) -> None:
        """Initialize the message.

        Args:
            has_file: True if there is a file to display, False if empty.
            file_count: Total number of files in the file list.
            file_index: Current file index (0-based).
        """
        super().__init__()
        self.has_file = has_file
        self.file_count = file_count
        self.file_index = file_index


class FileListChanged(Message):
    """Message posted when the file list or current index changes."""

    def __init__(self, file_count: int, file_index: int) -> None:
        """Initialize the message.

        Args:
            file_count: Total number of files in the file list.
            file_index: Current file index (0-based).
        """
        super().__init__()
        self.file_count = file_count
        self.file_index = file_index


class FileTrimChanged(Message):
    """Message posted when file content trimming state changes."""

    def __init__(self, visible_lines: int, total_lines: int, is_trimmed: bool) -> None:
        """Initialize the message.

        Args:
            visible_lines: Number of lines currently visible.
            total_lines: Total number of lines in the content.
            is_trimmed: Whether the content is currently trimmed.
        """
        super().__init__()
        self.visible_lines = visible_lines
        self.total_lines = total_lines
        self.is_trimmed = is_trimmed


@dataclass
class FileCacheEntry:
    """Cache entry for agent file output."""

    diff_output: str | None
    fetch_time: datetime


# Module-level cache for file outputs
file_cache: dict[str, FileCacheEntry] = {}


def get_cache_key(agent: Agent) -> str:
    """Generate a unique cache key for an agent's file output.

    Includes agent type, workspace, and raw_suffix (timestamp) to ensure
    different agent instances don't share cached files incorrectly.
    """
    parts = [agent.cl_name, agent.agent_type.value]
    if agent.workspace_num is not None:
        parts.append(str(agent.workspace_num))
    if agent.raw_suffix is not None:
        parts.append(agent.raw_suffix)
    return ":".join(parts)


_EXTENSION_TO_LEXER: dict[str, str] = {
    ".diff": "diff",
    ".patch": "diff",
    ".py": "python",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".sh": "bash",
    ".bash": "bash",
    ".js": "javascript",
    ".ts": "typescript",
    ".md": "markdown",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
}

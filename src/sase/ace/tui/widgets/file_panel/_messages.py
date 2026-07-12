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


class FileLineCountChanged(Message):
    """Message posted when file content line-count state changes."""

    def __init__(self, visible_lines: int, total_lines: int, capped: bool) -> None:
        """Initialize the message.

        Args:
            visible_lines: Number of lines currently visible.
            total_lines: Total number of lines in the content.
            capped: Whether the pathological-size render cap is active.
        """
        super().__init__()
        self.visible_lines = visible_lines
        self.total_lines = total_lines
        self.capped = capped


class LinkedDeltasRefreshed(Message):
    """Message posted when cached linked-repo deltas refreshed for an agent."""

    def __init__(self, agent_identity: tuple[object, ...]) -> None:
        super().__init__()
        self.agent_identity = agent_identity


@dataclass
class FileCacheEntry:
    """Cache entry for agent file output."""

    diff_output: str | None
    fetch_time: datetime


# Module-level cache for file outputs
file_cache: dict[str, FileCacheEntry] = {}


# Sentinel value used in file-panel page lists to represent the
# auto-refreshing primary live diff slot.
_LIVE_DIFF_SENTINEL = "__live_diff__"
COMMIT_DIFF_PREFIX = "__commit_diff__:"
LINKED_DIFF_PREFIX = "__linked_diff__:"


def commit_slot_id(index: int) -> str:
    """Return the file-list slot id for a persisted commit diff page."""
    return f"{COMMIT_DIFF_PREFIX}{index}"


def is_commit_slot(value: str) -> bool:
    """Return whether *value* is a persisted commit diff page slot id."""
    return value.startswith(COMMIT_DIFF_PREFIX)


def commit_slot_index(value: str) -> int:
    """Return the commit index encoded in a commit diff page slot id."""
    if not is_commit_slot(value):
        raise ValueError(f"not a commit diff slot: {value!r}")
    return int(value[len(COMMIT_DIFF_PREFIX) :])


def linked_slot_id(repo_name: str) -> str:
    """Return the file-list slot id for a linked-repo diff page."""
    return f"{LINKED_DIFF_PREFIX}{repo_name}"


def is_linked_slot(value: str) -> bool:
    """Return whether *value* is a linked-repo diff page slot id."""
    return value.startswith(LINKED_DIFF_PREFIX)


def linked_slot_repo_name(value: str) -> str:
    """Return the repo name encoded in a linked-repo diff page slot id."""
    if not is_linked_slot(value):
        raise ValueError(f"not a linked diff slot: {value!r}")
    return value[len(LINKED_DIFF_PREFIX) :]


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

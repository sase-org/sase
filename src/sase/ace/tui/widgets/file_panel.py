"""Agent file panel widget for the ace TUI."""

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from sase.gh_workspace import detect_vcs_type_for_project
from sase.running_field import get_workspace_directory
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from ..models.agent import Agent


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
class _FileCacheEntry:
    """Cache entry for agent file output."""

    diff_output: str | None
    fetch_time: datetime


# Module-level cache for file outputs
_file_cache: dict[str, _FileCacheEntry] = {}


def _get_cache_key(agent: Agent) -> str:
    """Generate a unique cache key for an agent's file output.

    Includes agent type and workspace to ensure different agents
    don't share cached files incorrectly.
    """
    if agent.workspace_num is not None:
        return f"{agent.cl_name}:{agent.agent_type.value}:{agent.workspace_num}"
    return f"{agent.cl_name}:{agent.agent_type.value}"


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


class AgentFilePanel(Static):
    """Bottom panel showing agent file output (diffs, markdown, etc.)."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the file panel."""
        super().__init__(**kwargs)
        self._current_agent: Agent | None = None
        self._current_worker: Worker[str | None] | None = None
        self._has_displayed_content: bool = False
        self._last_file_content: str | None = None
        self._is_background_refreshing: bool = False
        self._file_list: list[str] = []
        self._current_file_index: int = 0
        # Trim state
        self._total_line_count: int = 0
        self._visible_line_count: int = 0
        self._base_trim_size: int = 0
        self._is_trimmed: bool = False
        self._full_content: str | None = None
        self._full_content_lexer: str = "text"
        self._content_mode: str = "none"
        self._static_header_path: str | None = None

    def update_display(self, agent: Agent, stale_threshold_seconds: int = 10) -> None:
        """Update with agent file output.

        Args:
            agent: The Agent to display file for.
            stale_threshold_seconds: Files older than this are refetched.
        """
        self._reset_trim_state()
        self._current_agent = agent

        # Check cache
        cache_key = _get_cache_key(agent)
        cache_entry = _file_cache.get(cache_key)

        if cache_entry is not None:
            age_seconds = (datetime.now() - cache_entry.fetch_time).total_seconds()
            if age_seconds < stale_threshold_seconds:
                # Cache is fresh - use it directly
                self._display_file_with_timestamp(
                    cache_entry.diff_output,
                    cache_entry.fetch_time,
                    post_visibility_message=True,
                )
                return

            # Cache is stale - display stale content while fetching in background
            self._is_background_refreshing = True
            self._display_file_with_timestamp(
                cache_entry.diff_output,
                cache_entry.fetch_time,
                post_visibility_message=True,
                is_stale=True,
            )
        else:
            # No cache - show loading for first-time loads
            self._show_loading()

        # Cancel any existing worker
        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        # Start background worker using closure to capture agent
        def fetch_task() -> str | None:
            return self._fetch_file_in_background(agent)

        self._current_worker = self.run_worker(fetch_task, thread=True)

    def set_file_list(self, files: list[str]) -> None:
        """Store the file list, reset index to 0, and display the first file.

        Args:
            files: Ordered list of file paths to make available for cycling.
        """
        self._reset_trim_state()
        if files == self._file_list:
            return
        self._file_list = list(files)
        self._current_file_index = 0
        self.post_message(
            FileListChanged(file_count=len(self._file_list), file_index=0)
        )
        if files:
            self._display_file_at_current_index()

    def next_file(self) -> None:
        """Cycle to the next file in the list (wraps around)."""
        if len(self._file_list) <= 1:
            return
        self._current_file_index = (self._current_file_index + 1) % len(self._file_list)
        self._display_file_at_current_index()
        self.post_message(
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
        )

    def prev_file(self) -> None:
        """Cycle to the previous file in the list (wraps around)."""
        if len(self._file_list) <= 1:
            return
        self._current_file_index = (self._current_file_index - 1) % len(self._file_list)
        self._display_file_at_current_index()
        self.post_message(
            FileListChanged(
                file_count=len(self._file_list),
                file_index=self._current_file_index,
            )
        )

    @property
    def current_file_count(self) -> int:
        """Return the number of files in the file list."""
        return len(self._file_list)

    @property
    def current_file_index(self) -> int:
        """Return the current file index (0-based)."""
        return self._current_file_index

    def _display_file_at_current_index(self) -> None:
        """Display the file at the current index using static file display."""
        if not self._file_list:
            return
        self.display_static_file(self._file_list[self._current_file_index])

    def _post_file_visibility(self, has_file: bool) -> None:
        """Post a FileVisibilityChanged message with current file list state."""
        file_count = len(self._file_list) if self._file_list else (1 if has_file else 0)
        self.post_message(
            FileVisibilityChanged(
                has_file=has_file,
                file_count=file_count,
                file_index=self._current_file_index,
            )
        )

    def _compute_trim_size(self) -> int:
        """Compute the number of lines to show based on container height.

        Returns:
            The trim size, or 0 if container is unavailable.
        """
        container = self._get_scroll_container()
        if container is None:
            return 0
        try:
            height = container.scrollable_content_region.height
        except Exception:
            return 0
        return max(10, height - 4)

    def _reset_trim_state(self) -> None:
        """Reset all trim-related fields to defaults."""
        self._total_line_count = 0
        self._visible_line_count = 0
        self._base_trim_size = 0
        self._is_trimmed = False
        self._full_content = None
        self._full_content_lexer = "text"
        self._content_mode = "none"
        self._static_header_path = None

    def _count_lines(self, content: str) -> int:
        """Count the number of lines in content.

        Args:
            content: The text content.

        Returns:
            The line count.
        """
        return content.count("\n") + (1 if not content.endswith("\n") else 0)

    def _post_trim_changed(self) -> None:
        """Post a FileTrimChanged message with current trim state."""
        self.post_message(
            FileTrimChanged(
                visible_lines=self._visible_line_count,
                total_lines=self._total_line_count,
                is_trimmed=self._is_trimmed,
            )
        )

    def _render_trimmed_content(self) -> None:
        """Re-render full_content with current trim state."""
        if self._full_content is None:
            return

        visible = self._visible_line_count
        total = self._total_line_count

        if self._content_mode == "static":
            header = Text(
                self._static_header_path or "", style="bold #D7AF5F underline"
            )
            syntax = Syntax(
                self._full_content,
                self._full_content_lexer,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
                line_range=(1, visible),
            )
            remaining = total - visible
            indicator = Text(
                f"\n  \u25be {remaining} more lines below",
                style="dim italic #87D7FF",
            )
            self.update(Group(header, Text(""), syntax, indicator))
        elif self._content_mode in ("diff", "static_diff"):
            if self._content_mode == "static_diff":
                header = Text(
                    self._static_header_path or "",
                    style="bold #D7AF5F underline",
                )
                syntax = Syntax(
                    self._full_content,
                    "diff",
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True,
                    line_range=(1, visible),
                )
                remaining = total - visible
                indicator = Text(
                    f"\n  \u25be {remaining} more lines below",
                    style="dim italic #87D7FF",
                )
                self.update(Group(header, Text(""), syntax, indicator))
            else:
                syntax = Syntax(
                    self._full_content,
                    "diff",
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True,
                    line_range=(1, visible),
                )
                remaining = total - visible
                indicator = Text(
                    f"\n  \u25be {remaining} more lines below",
                    style="dim italic #87D7FF",
                )
                self.update(Group(syntax, indicator))

        self._is_trimmed = True
        self._post_trim_changed()

    @property
    def is_trimmed(self) -> bool:
        """Whether the content is currently trimmed."""
        return self._is_trimmed

    def expand_by_page(self) -> None:
        """Expand visible lines by one page (base_trim_size)."""
        if not self._full_content or not self._is_trimmed:
            return
        self._visible_line_count = min(
            self._visible_line_count + self._base_trim_size,
            self._total_line_count,
        )
        if self._visible_line_count >= self._total_line_count:
            self._visible_line_count = self._total_line_count
            self._is_trimmed = False
            self._render_full_content()
        else:
            self._render_trimmed_content()

    def collapse_by_page(self) -> None:
        """Collapse visible lines by one page (base_trim_size)."""
        if not self._full_content:
            return
        scroll_pos = self._save_scroll_position()
        self._visible_line_count = max(
            self._visible_line_count - self._base_trim_size,
            self._base_trim_size,
        )
        if self._visible_line_count < self._total_line_count:
            self._is_trimmed = True
            self._render_trimmed_content()
        else:
            self._is_trimmed = False
            self._render_full_content()
        self._restore_scroll_position(scroll_pos)

    def reset_trim(self) -> None:
        """Reset trim to the default page size for current viewport."""
        if not self._full_content:
            return
        self._base_trim_size = self._compute_trim_size()
        self._visible_line_count = min(self._base_trim_size, self._total_line_count)
        if self._visible_line_count < self._total_line_count:
            self._is_trimmed = True
            self._render_trimmed_content()
        else:
            self._is_trimmed = False
            self._render_full_content()

    def show_all_lines(self) -> None:
        """Show all lines (remove trimming)."""
        if not self._full_content:
            return
        self._visible_line_count = self._total_line_count
        self._is_trimmed = False
        self._render_full_content()

    def _render_full_content(self) -> None:
        """Re-render full_content without trimming."""
        if self._full_content is None:
            return

        if self._content_mode == "static":
            header = Text(
                self._static_header_path or "", style="bold #D7AF5F underline"
            )
            syntax = Syntax(
                self._full_content,
                self._full_content_lexer,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
            )
            self.update(Group(header, Text(""), syntax))
        elif self._content_mode in ("diff", "static_diff"):
            if self._content_mode == "static_diff":
                header = Text(
                    self._static_header_path or "",
                    style="bold #D7AF5F underline",
                )
                syntax = Syntax(
                    self._full_content,
                    "diff",
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True,
                )
                self.update(Group(header, Text(""), syntax))
            else:
                syntax = Syntax(
                    self._full_content,
                    "diff",
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True,
                )
                self.update(syntax)

        self._post_trim_changed()

    def refresh_file(self, agent: Agent) -> None:
        """Force refresh the file for an agent.

        Args:
            agent: The Agent to refresh file for.
        """
        self._current_agent = agent

        # Check for existing cache to display while refreshing
        cache_key = _get_cache_key(agent)
        cache_entry = _file_cache.get(cache_key)

        if cache_entry is not None:
            # Show existing content with "(refreshing...)" indicator
            self._is_background_refreshing = True
            self._display_file_with_timestamp(
                cache_entry.diff_output,
                cache_entry.fetch_time,
                post_visibility_message=True,
                is_stale=True,
            )
        else:
            # No cache - show loading for first-time loads
            self._show_loading()

        # Cancel any existing worker
        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        # Start background worker using closure to capture agent
        def fetch_task() -> str | None:
            return self._fetch_file_in_background(agent)

        self._current_worker = self.run_worker(fetch_task, thread=True)

    def _show_loading(self) -> None:
        """Display loading indicator only if panel was previously visible."""
        if not self._has_displayed_content:
            return
        text = Text()
        text.append("Loading file...\n", style="bold #87D7FF")
        text.append("Please wait while fetching changes.", style="dim")
        self.update(text)

    def _get_scroll_container(self) -> VerticalScroll | None:
        """Get the parent scroll container for this file panel.

        Returns:
            The VerticalScroll container, or None if not found.
        """
        try:
            return self.app.query_one("#agent-file-scroll", VerticalScroll)
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
            self.call_after_refresh(
                lambda: container.scroll_to(y=position, animate=False)
            )

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
            self._post_file_visibility(has_file=diff_output is not None)

        # Build refresh indicator if stale and background refreshing
        refresh_indicator = ""
        if is_stale and self._is_background_refreshing:
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

            # Compute trimming
            total = self._count_lines(diff_with_header)
            trim_size = self._compute_trim_size()
            self._total_line_count = total
            self._base_trim_size = trim_size

            if trim_size > 0 and total > trim_size:
                self._visible_line_count = trim_size
                self._is_trimmed = True
                syntax = Syntax(
                    diff_with_header,
                    "diff",
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True,
                    line_range=(1, trim_size),
                )
                remaining = total - trim_size
                indicator = Text(
                    f"\n  \u25be {remaining} more lines below",
                    style="dim italic #87D7FF",
                )
                self.update(Group(syntax, indicator))
            else:
                self._visible_line_count = total
                self._is_trimmed = False
                syntax = Syntax(
                    diff_with_header,
                    "diff",
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True,
                )
                self.update(syntax)

            self._post_trim_changed()
        else:
            text = Text()
            text.append("Last fetched: ", style="dim")
            text.append(fetch_time.strftime("%H:%M:%S"), style="#87D7FF")
            if refresh_indicator:
                text.append(refresh_indicator, style="dim italic")
            text.append("\n\n")
            text.append("No changes detected.\n", style="dim italic")
            self.update(text)

        self._has_displayed_content = True

    def _fetch_file_in_background(self, agent: Agent) -> str | None:
        """Fetch file output in background thread.

        Args:
            agent: The agent to get file for.

        Returns:
            File output string, or None if unavailable.
        """
        diff_output = self._get_agent_diff(agent)

        # Store in cache
        cache_key = _get_cache_key(agent)
        _file_cache[cache_key] = _FileCacheEntry(
            diff_output=diff_output,
            fetch_time=datetime.now(),
        )

        return diff_output

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes."""
        if event.worker != self._current_worker:
            return

        # Always clear background refreshing flag when worker completes
        self._is_background_refreshing = False

        if event.state == WorkerState.SUCCESS:
            # Worker completed - display result from cache
            if self._current_agent:
                cache_key = _get_cache_key(self._current_agent)
                if cache_key in _file_cache:
                    cache_entry = _file_cache[cache_key]

                    # Skip update if content hasn't changed (but only
                    # if we've displayed before — on first load, None==None
                    # would suppress the visibility message that hides us)
                    if (
                        self._has_displayed_content
                        and cache_entry.diff_output == self._last_file_content
                    ):
                        # Content unchanged - just update timestamp without scroll reset
                        # Re-display to update the timestamp (removes "refreshing...")
                        # Preserve user's visible line count (e.g. if they
                        # paged down) instead of resetting to _base_trim_size
                        saved_visible = self._visible_line_count
                        scroll_pos = self._save_scroll_position()
                        self._display_file_with_timestamp(
                            cache_entry.diff_output,
                            cache_entry.fetch_time,
                            post_visibility_message=False,
                        )
                        self._visible_line_count = saved_visible
                        self._restore_scroll_position(scroll_pos)
                    else:
                        # Content changed - save scroll, update, restore scroll
                        scroll_pos = self._save_scroll_position()
                        self._display_file_with_timestamp(
                            cache_entry.diff_output, cache_entry.fetch_time
                        )
                        self._restore_scroll_position(scroll_pos)
        elif event.state == WorkerState.ERROR:
            # Show error state
            text = Text()
            text.append("Error fetching file\n", style="bold red")
            text.append("The diff command failed or timed out.", style="dim")
            self.update(text)
        elif event.state == WorkerState.CANCELLED:
            # Cancelled - do nothing, new worker will handle display
            pass

    def _get_agent_diff(self, agent: Agent) -> str | None:
        """Get diff output for an agent.

        For RUNNING type agents, use workspace_num to find directory.
        For other agents, try to determine workspace from project file.

        Args:
            agent: The agent to get diff for.

        Returns:
            Diff output string, or None if unavailable.
        """
        try:
            # Get project basename from file path
            project_basename = Path(agent.project_file).stem

            if agent.workspace_num:
                workspace_dir = get_workspace_directory(
                    project_basename, agent.workspace_num
                )
            else:
                # Use primary workspace for other agent types
                # Loop agents use workspaces 100+, but we show diff from main
                workspace_dir = get_workspace_directory(project_basename, 1)

            # Detect VCS type from project config rather than filesystem
            # detection.  CITC/fig hg workspaces may lack a physical .hg
            # directory, so detect_vcs() (which walks the directory tree
            # looking for .hg/.git) can return None even though hg commands
            # work fine.  detect_vcs_type_for_project() uses the .gp file
            # configuration (WORKSPACE_DIR + .git check) which is reliable
            # for both git and hg projects.
            vcs_type = detect_vcs_type_for_project(
                os.path.expanduser(agent.project_file)
            )
            if vcs_type == "git":
                from sase.git_utils import git_diff_with_untracked

                return git_diff_with_untracked(workspace_dir, timeout=10)
            elif vcs_type == "hg":
                diff_cmd = ["hg", "diff"]
            else:
                return None

            result = subprocess.run(
                diff_cmd,
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
            return None

        except subprocess.TimeoutExpired:
            return None
        except subprocess.CalledProcessError:
            return None
        except RuntimeError:
            # sase_hg_get_workspace command failed
            return None
        except Exception:
            return None

    def get_current_file_path(self) -> str | None:
        """Return the expanded path of the currently displayed file, or None."""
        if self._file_list:
            return os.path.expanduser(self._file_list[self._current_file_index])
        return None

    def get_current_content(self) -> str | None:
        """Return the last displayed file content, or None."""
        return self._last_file_content

    def show_empty(self) -> None:
        """Show empty state."""
        self._reset_trim_state()
        self._has_displayed_content = False
        text = Text("No agent selected", style="dim italic")
        self.update(text)

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
            self.update(text)
            self._post_file_visibility(has_file=False)
            return

        if not diff_content.strip():
            text = Text("Diff file is empty.\n", style="dim italic")
            self.update(text)
            self._post_file_visibility(has_file=False)
            return

        # Display diff with file path header
        diff_with_header = f"# Static diff (from saved file)\n\n{diff_content}"

        # Store content for future re-render
        self._full_content = diff_with_header
        self._full_content_lexer = "diff"
        self._content_mode = "static_diff"
        self._static_header_path = expanded_path

        # Compute trimming
        total = self._count_lines(diff_with_header)
        trim_size = self._compute_trim_size()
        self._total_line_count = total
        self._base_trim_size = trim_size

        header = Text(expanded_path, style="bold #D7AF5F underline")

        if trim_size > 0 and total > trim_size:
            self._visible_line_count = trim_size
            self._is_trimmed = True
            syntax = Syntax(
                diff_with_header,
                "diff",
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
                line_range=(1, trim_size),
            )
            remaining = total - trim_size
            indicator = Text(
                f"\n  \u25be {remaining} more lines below",
                style="dim italic #87D7FF",
            )
            self.update(Group(header, Text(""), syntax, indicator))
        else:
            self._visible_line_count = total
            self._is_trimmed = False
            syntax = Syntax(
                diff_with_header,
                "diff",
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
            )
            self.update(Group(header, Text(""), syntax))

        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)
        self._post_trim_changed()

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
            self.update(text)
            self._post_file_visibility(has_file=False)
            return

        if not content.strip():
            text = Text("File is empty.\n", style="dim italic")
            self.update(text)
            self._post_file_visibility(has_file=False)
            return

        # Detect lexer from file extension
        _, ext = os.path.splitext(expanded_path)
        lexer = _EXTENSION_TO_LEXER.get(ext.lower(), "text")

        # Store content for future re-render
        self._full_content = content
        self._full_content_lexer = lexer
        self._content_mode = "static"
        self._static_header_path = expanded_path

        # Compute trimming
        total = self._count_lines(content)
        trim_size = self._compute_trim_size()
        self._total_line_count = total
        self._base_trim_size = trim_size

        header = Text(expanded_path, style="bold #D7AF5F underline")

        if trim_size > 0 and total > trim_size:
            self._visible_line_count = trim_size
            self._is_trimmed = True
            syntax = Syntax(
                content,
                lexer,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
                line_range=(1, trim_size),
            )
            remaining = total - trim_size
            indicator = Text(
                f"\n  \u25be {remaining} more lines below",
                style="dim italic #87D7FF",
            )
            self.update(Group(header, Text(""), syntax, indicator))
        else:
            self._visible_line_count = total
            self._is_trimmed = False
            syntax = Syntax(
                content,
                lexer,
                theme="monokai",
                line_numbers=True,
                word_wrap=True,
            )
            self.update(Group(header, Text(""), syntax))

        self._has_displayed_content = True
        self._post_file_visibility(has_file=True)
        self._post_trim_changed()

"""Agent thinking panel widget for the ace TUI."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sase.sase_utils import EASTERN_TZ

from rich.text import Text
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.thinking import (
    ThinkingBlock,
    parse_thinking_blocks_multi,
    read_gemini_log,
    resolve_agent_sessions,
)
from sase.llm_provider.registry import get_default_provider_name


class ThinkingVisibilityChanged(Message):
    """Message posted when thinking panel visibility should change."""

    def __init__(self, has_thinking: bool) -> None:
        """Initialize the message.

        Args:
            has_thinking: True if there are thinking blocks to display.
        """
        super().__init__()
        self.has_thinking = has_thinking


@dataclass
class _ThinkingCacheEntry:
    """Cache entry for agent thinking blocks."""

    blocks: list[ThinkingBlock] | None
    fetch_time: datetime
    source: str = "claude"


# Module-level cache for thinking outputs
_thinking_cache: dict[str, _ThinkingCacheEntry] = {}


def get_cache_key(agent: Agent) -> str:
    """Generate a unique cache key for an agent's thinking output.

    Includes agent type, workspace, and raw_suffix to ensure different
    agents don't share cached thinking incorrectly.
    """
    parts = [agent.cl_name, agent.agent_type.value]
    if agent.workspace_num is not None:
        parts.append(str(agent.workspace_num))
    if agent.raw_suffix:
        parts.append(agent.raw_suffix)
    return ":".join(parts)


def _format_timestamp(iso_str: str) -> str:
    """Format an ISO timestamp to HH:MM:SS display.

    Args:
        iso_str: ISO 8601 timestamp (e.g., "2026-02-19T18:03:06.794Z").

    Returns:
        Formatted time string like "18:03:06", or "??:??:??" on failure.
    """
    try:
        # Handle Z suffix (UTC indicator)
        cleaned = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        dt = dt.astimezone(EASTERN_TZ)
        return dt.strftime("%H:%M:%S")
    except (ValueError, AttributeError):
        return "??:??:??"


def _format_char_count(total: int) -> str:
    """Format a character count for display.

    Args:
        total: Total character count.

    Returns:
        Formatted string like "8.2k" or "500".
    """
    if total >= 1000:
        value = total / 1000
        # Show one decimal place, but drop trailing zero
        if value == int(value):
            return f"{int(value)}k"
        return f"{value:.1f}k"
    return str(total)


class AgentThinkingPanel(Static):
    """Panel showing Claude's thinking blocks for the selected agent."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the thinking panel."""
        super().__init__(**kwargs)
        self._current_agent: Agent | None = None
        self._current_worker: Worker[list[ThinkingBlock] | None] | None = None
        self._has_displayed_content: bool = False
        self._last_blocks: list[ThinkingBlock] | None = None
        self._is_background_refreshing: bool = False

    def update_display(self, agent: Agent, stale_threshold_seconds: int = 10) -> None:
        """Update with agent thinking blocks.

        Args:
            agent: The Agent to display thinking for.
            stale_threshold_seconds: Entries older than this are refetched.
        """
        self._current_agent = agent

        # Check cache
        cache_key = get_cache_key(agent)
        cache_entry = _thinking_cache.get(cache_key)

        if cache_entry is not None:
            age_seconds = (datetime.now() - cache_entry.fetch_time).total_seconds()
            if age_seconds < stale_threshold_seconds:
                # Cache is fresh - use it directly
                self._display_thinking_with_timestamp(
                    cache_entry.blocks,
                    cache_entry.fetch_time,
                    post_visibility_message=True,
                    source=cache_entry.source,
                )
                return

            # Cache is stale - display stale content while fetching in background
            self._is_background_refreshing = True
            self._display_thinking_with_timestamp(
                cache_entry.blocks,
                cache_entry.fetch_time,
                post_visibility_message=True,
                is_stale=True,
                source=cache_entry.source,
            )
        else:
            # No cache - show loading for first-time loads
            self._show_loading()

        # Cancel any existing worker
        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        # Start background worker using closure to capture agent
        def fetch_task() -> list[ThinkingBlock] | None:
            return self._fetch_thinking_in_background(agent)

        self._current_worker = self.run_worker(fetch_task, thread=True)

    def refresh_thinking(self, agent: Agent) -> None:
        """Force refresh the thinking blocks for an agent.

        Args:
            agent: The Agent to refresh thinking for.
        """
        self._current_agent = agent

        # Check for existing cache to display while refreshing
        cache_key = get_cache_key(agent)
        cache_entry = _thinking_cache.get(cache_key)

        if cache_entry is not None:
            # Show existing content with "(refreshing...)" indicator
            self._is_background_refreshing = True
            self._display_thinking_with_timestamp(
                cache_entry.blocks,
                cache_entry.fetch_time,
                post_visibility_message=True,
                is_stale=True,
                source=cache_entry.source,
            )
        else:
            # No cache - show loading for first-time loads
            self._show_loading()

        # Cancel any existing worker
        if self._current_worker is not None and self._current_worker.is_running:
            self._current_worker.cancel()

        # Start background worker using closure to capture agent
        def fetch_task() -> list[ThinkingBlock] | None:
            return self._fetch_thinking_in_background(agent)

        self._current_worker = self.run_worker(fetch_task, thread=True)

    def get_thinking_text(self) -> str | None:
        """Concatenate all thinking block texts, or return None if no blocks."""
        if not self._last_blocks:
            return None
        separator = "\n\n" + "=" * 60 + "\n\n"
        return separator.join(block.text for block in self._last_blocks)

    def show_empty(self) -> None:
        """Show empty state."""
        self._has_displayed_content = False
        text = Text("No agent selected", style="dim italic")
        self.update(text)

    def _show_loading(self) -> None:
        """Display loading indicator only if panel was previously visible."""
        if not self._has_displayed_content:
            return
        text = Text("Loading thinking blocks...", style="bold #AF87D7")
        self.update(text)

    def _get_scroll_container(self) -> VerticalScroll | None:
        """Get the parent scroll container for this thinking panel.

        Returns:
            The VerticalScroll container, or None if not found.
        """
        try:
            return self.app.query_one("#agent-thinking-scroll", VerticalScroll)
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

    def _display_thinking_with_timestamp(
        self,
        blocks: list[ThinkingBlock] | None,
        fetch_time: datetime,
        *,
        post_visibility_message: bool = True,
        is_stale: bool = False,
        source: str = "claude",
    ) -> None:
        """Display thinking blocks with fetch timestamp.

        Args:
            blocks: The thinking blocks, None if no session, [] if empty.
            fetch_time: When the thinking was fetched.
            post_visibility_message: Whether to post visibility change message.
            is_stale: Whether the content is stale (showing while refreshing).
            source: Data source — "claude" or "gemini".
        """
        # Track last displayed blocks for change detection
        self._last_blocks = blocks

        if blocks is None:
            # No session found
            text = Text("No thinking data available", style="dim italic")
            self.update(text)
            if post_visibility_message:
                self.post_message(ThinkingVisibilityChanged(has_thinking=False))
            return

        if not blocks:
            # Session found but no thinking blocks
            text = Text("No thinking blocks in this session", style="dim italic")
            self.update(text)
            if post_visibility_message:
                self.post_message(ThinkingVisibilityChanged(has_thinking=False))
            return

        # Source-dependent styling
        is_gemini = source == "gemini"
        header_text = "GEMINI THINKING" if is_gemini else "CLAUDE THINKING"
        header_color = "#4285F4" if is_gemini else "#AF87D7"
        border_color = f"dim {header_color}"
        content_color = "#B4C7E7" if is_gemini else "#D7D7FF"

        # Build refresh indicator if stale and background refreshing
        refresh_indicator = ""
        if is_stale and self._is_background_refreshing:
            refresh_indicator = " (refreshing...)"

        # Calculate total chars across all blocks
        total_chars = sum(len(b.text) for b in blocks)

        # Build Rich Text output
        output = Text()

        # Header line
        output.append(header_text, style=f"bold {header_color} underline")
        if refresh_indicator:
            output.append(refresh_indicator, style="dim italic")
        output.append("\n")

        # Summary line
        block_word = "block" if len(blocks) == 1 else "blocks"
        output.append(
            f"{len(blocks)} thinking {block_word} · "
            f"{_format_char_count(total_chars)} chars\n\n",
            style="dim",
        )

        # Render each block
        for block in blocks:
            ts_display = _format_timestamp(block.timestamp)

            # Build top border content: " #N · HH:MM:SS "
            top_label = f" #{block.index} · {ts_display} "

            # Add action if present
            if block.following_action:
                action_text = f"→ {block.following_action} "
            else:
                action_text = ""

            # Top border: ╭─ label ─── action ──╮
            # Fixed bottom width of 46 chars; top border adapts
            border_min = len(top_label) + len(action_text) + 4  # ╭─ ... ──╮
            top_width = max(46, border_min)
            fill_count = (
                top_width - 3 - len(top_label) - len(action_text)
            )  # -3 for ╭─...╮
            fill = "─" * max(fill_count, 3)

            # Build top border with mixed styling
            output.append("╭─", style=border_color)
            output.append(top_label, style=border_color)
            output.append(fill[:3], style=border_color)  # separator
            if action_text:
                output.append(" ", style=border_color)
                output.append(action_text, style="#87D7FF")
                remaining_fill = fill_count - 4  # account for " " + space in action
                if remaining_fill > 0:
                    output.append("─" * remaining_fill, style=border_color)
            else:
                if fill_count > 3:
                    output.append(fill[3:], style=border_color)
            output.append("╮\n", style=border_color)

            # Block content - show full text, no truncation
            for line in block.text.splitlines():
                output.append("│", style=border_color)
                output.append(f" {line}", style=content_color)
                output.append("\n")

            # Bottom border: ╰──...──╯ (fixed 46 chars)
            bottom_fill = "─" * 44  # 46 - 2 for ╰╯
            output.append(f"╰{bottom_fill}╯\n\n", style=border_color)

        if post_visibility_message:
            self.post_message(ThinkingVisibilityChanged(has_thinking=True))

        self.update(output)
        self._has_displayed_content = True

    def _fetch_thinking_in_background(self, agent: Agent) -> list[ThinkingBlock] | None:
        """Fetch thinking blocks in background thread.

        Args:
            agent: The agent to get thinking for.

        Returns:
            List of ThinkingBlock, None if no session, [] if no blocks.
        """
        source = "claude"
        session_paths = resolve_agent_sessions(agent, since=agent.start_time)
        if not session_paths:
            # No Claude session — try Gemini log if default provider is gemini
            try:
                provider_name = get_default_provider_name()
            except Exception:
                provider_name = ""
            if provider_name == "gemini":
                blocks = read_gemini_log()
                source = "gemini"
            else:
                blocks = None
        else:
            blocks = parse_thinking_blocks_multi(session_paths)

        # Store in cache
        cache_key = get_cache_key(agent)
        _thinking_cache[cache_key] = _ThinkingCacheEntry(
            blocks=blocks,
            fetch_time=datetime.now(),
            source=source,
        )

        return blocks

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes."""
        if event.worker != self._current_worker:
            return

        # Always clear background refreshing flag when worker completes
        self._is_background_refreshing = False

        if event.state == WorkerState.SUCCESS:
            # Worker completed - display result from cache
            if self._current_agent:
                cache_key = get_cache_key(self._current_agent)
                if cache_key in _thinking_cache:
                    cache_entry = _thinking_cache[cache_key]

                    # Skip update if content hasn't changed
                    if cache_entry.blocks == self._last_blocks:
                        # Content unchanged - just remove "refreshing..." indicator
                        scroll_pos = self._save_scroll_position()
                        self._display_thinking_with_timestamp(
                            cache_entry.blocks,
                            cache_entry.fetch_time,
                            post_visibility_message=False,
                            source=cache_entry.source,
                        )
                        self._restore_scroll_position(scroll_pos)
                    else:
                        # Content changed - save scroll, update, restore scroll
                        scroll_pos = self._save_scroll_position()
                        self._display_thinking_with_timestamp(
                            cache_entry.blocks,
                            cache_entry.fetch_time,
                            source=cache_entry.source,
                        )
                        self._restore_scroll_position(scroll_pos)
        elif event.state == WorkerState.ERROR:
            # Show error state
            text = Text()
            text.append("Error fetching thinking blocks\n", style="bold red")
            text.append("Failed to parse session transcript.", style="dim")
            self.update(text)
        elif event.state == WorkerState.CANCELLED:
            # Cancelled - do nothing, new worker will handle display
            pass

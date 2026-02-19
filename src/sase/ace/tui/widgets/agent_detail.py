"""Agent detail widget for the ace TUI."""

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from ..models.agent import Agent
from .file_panel import AgentFilePanel, FileVisibilityChanged
from .prompt_panel import AgentPromptPanel
from .thinking_panel import AgentThinkingPanel, ThinkingVisibilityChanged


class AgentDetail(Static):
    """Combined widget with prompt and file panels."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the agent detail view."""
        super().__init__(**kwargs)
        self._layout_swapped: bool = False
        self._force_thinking: bool = False
        self._thinking_auto_shown: bool = False
        self._current_agent: Agent | None = None

    def compose(self) -> ComposeResult:
        """Compose the two-panel layout (prompt and file)."""
        with Vertical(id="agent-detail-layout"):
            with VerticalScroll(id="agent-prompt-scroll"):
                yield AgentPromptPanel(id="agent-prompt-panel")
            with VerticalScroll(id="agent-file-scroll"):
                yield AgentFilePanel(id="agent-file-panel")
            with VerticalScroll(id="agent-thinking-scroll", classes="hidden"):
                yield AgentThinkingPanel(id="agent-thinking-panel")

    def _auto_show_thinking(self, agent: Agent) -> None:
        """Auto-show thinking panel as fallback when file has no content.

        Args:
            agent: The Agent to display thinking for.
        """
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        thinking_scroll = self.query_one("#agent-thinking-scroll", VerticalScroll)
        thinking_panel = self.query_one("#agent-thinking-panel", AgentThinkingPanel)
        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)

        file_scroll.add_class("hidden")
        thinking_scroll.remove_class("hidden")
        prompt_scroll.remove_class("expanded")

        if self._layout_swapped:
            thinking_scroll.add_class("layout-secondary")
            prompt_scroll.add_class("layout-priority")
        else:
            thinking_scroll.remove_class("layout-secondary")
            prompt_scroll.remove_class("layout-priority")

        self._thinking_auto_shown = True
        thinking_panel.update_display(agent)

    def update_display(self, agent: Agent, stale_threshold_seconds: int = 10) -> None:
        """Update panels with agent information.

        For NO CHANGES agents, shows only prompt panel (with reply embedded).
        For NEW CL and NEW PROPOSAL agents, shows prompt and static file panels.
        For running agents, shows prompt and auto-refreshing file panels.

        Args:
            agent: The Agent to display.
            stale_threshold_seconds: Diffs older than this are refetched.
        """
        prompt_panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)

        # Detect agent change and reset auto-shown thinking flag
        prev_agent = self._current_agent
        self._current_agent = agent
        if (
            self._thinking_auto_shown
            and prev_agent is not None
            and prev_agent.identity != agent.identity
        ):
            self._thinking_auto_shown = False
            thinking_scroll = self.query_one("#agent-thinking-scroll", VerticalScroll)
            thinking_scroll.add_class("hidden")

        prompt_panel.update_display(agent)

        # When thinking panel is visible, keep it showing and just refresh data
        if self._force_thinking or self._thinking_auto_shown:
            thinking_panel = self.query_one("#agent-thinking-panel", AgentThinkingPanel)
            thinking_panel.update_display(
                agent, stale_threshold_seconds=stale_threshold_seconds
            )
            # Still update file panel in background (for when thinking is toggled off)
            if agent.status in ("RUNNING", "WAITING INPUT"):
                file_panel.update_display(
                    agent, stale_threshold_seconds=stale_threshold_seconds
                )
            return

        # Bash/python workflow steps don't have files - show thinking as fallback
        if agent.is_workflow_child and agent.step_type in ("bash", "python"):
            self._auto_show_thinking(agent)
            return

        if agent.status in ("RUNNING", "WAITING INPUT"):
            # Show auto-refreshing file panel for active agents
            # Don't change visibility here - let update_display() handle it
            # via FileVisibilityChanged message after fetching/validating the file
            file_panel.update_display(
                agent, stale_threshold_seconds=stale_threshold_seconds
            )
        else:
            # DONE, FAILED, etc.
            if agent.diff_path:
                file_panel.display_static_file(agent.diff_path)
            else:
                self._auto_show_thinking(agent)

    def show_empty(self) -> None:
        """Show empty state for all panels."""
        prompt_panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        thinking_panel = self.query_one("#agent-thinking-panel", AgentThinkingPanel)

        prompt_panel.show_empty()
        file_panel.show_empty()
        thinking_panel.show_empty()

        # Hide file and thinking panels when no agent is selected
        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        thinking_scroll = self.query_one("#agent-thinking-scroll", VerticalScroll)
        file_scroll.add_class("hidden")
        thinking_scroll.add_class("hidden")
        prompt_scroll.add_class("expanded")
        self._force_thinking = False
        self._thinking_auto_shown = False

    def refresh_current_file(self, agent: Agent) -> None:
        """Force refresh the file for the given agent.

        Args:
            agent: The Agent to refresh file for.
        """
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.refresh_file(agent)

    def toggle_thinking(self, agent: Agent) -> None:
        """Toggle between file panel and thinking panel.

        Args:
            agent: The currently selected agent.
        """
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        thinking_scroll = self.query_one("#agent-thinking-scroll", VerticalScroll)
        thinking_panel = self.query_one("#agent-thinking-panel", AgentThinkingPanel)

        if not self._force_thinking:
            # Toggle ON: hide file, show thinking
            file_scroll.add_class("hidden")
            thinking_scroll.remove_class("hidden")

            # Mirror layout classes from file to thinking
            if self._layout_swapped:
                thinking_scroll.add_class("layout-secondary")
            else:
                thinking_scroll.remove_class("layout-secondary")

            self._force_thinking = True
            self._thinking_auto_shown = False
            thinking_panel.update_display(agent)
        else:
            # Toggle OFF: re-evaluate what to show
            self._force_thinking = False
            self._thinking_auto_shown = False
            thinking_scroll.add_class("hidden")
            file_scroll.remove_class("hidden")
            self.update_display(agent)

    def on_thinking_visibility_changed(
        self, message: ThinkingVisibilityChanged
    ) -> None:
        """Handle thinking panel visibility changes.

        Args:
            message: The visibility change message.
        """
        if not self._force_thinking and not self._thinking_auto_shown:
            return

        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
        thinking_scroll = self.query_one("#agent-thinking-scroll", VerticalScroll)

        if message.has_thinking:
            thinking_scroll.remove_class("hidden")
            prompt_scroll.remove_class("expanded")
            if self._layout_swapped:
                prompt_scroll.add_class("layout-priority")
                thinking_scroll.add_class("layout-secondary")
        else:
            thinking_scroll.add_class("hidden")
            prompt_scroll.add_class("expanded")
            prompt_scroll.remove_class("layout-priority")
            thinking_scroll.remove_class("layout-secondary")
            # Clear auto-shown flag since there's no thinking content
            if self._thinking_auto_shown:
                self._thinking_auto_shown = False

    def on_file_visibility_changed(self, message: FileVisibilityChanged) -> None:
        """Handle file panel visibility changes.

        Args:
            message: The visibility change message.
        """
        # Skip file visibility changes when user forced thinking
        if self._force_thinking:
            return

        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)

        if message.has_file:
            if self._thinking_auto_shown:
                # File appeared - switch from auto-shown thinking to file
                thinking_scroll = self.query_one(
                    "#agent-thinking-scroll", VerticalScroll
                )
                thinking_scroll.add_class("hidden")
                self._thinking_auto_shown = False
            # Show file panel
            file_scroll.remove_class("hidden")
            prompt_scroll.remove_class("expanded")
            # Restore layout preference if swapped
            if self._layout_swapped:
                prompt_scroll.add_class("layout-priority")
                file_scroll.add_class("layout-secondary")
        else:
            # File has no content - auto-show thinking as fallback
            if self._current_agent is not None:
                self._auto_show_thinking(self._current_agent)
            else:
                # No agent context, just expand prompt
                file_scroll.add_class("hidden")
                prompt_scroll.add_class("expanded")
                prompt_scroll.remove_class("layout-priority")
                file_scroll.remove_class("layout-secondary")

    def toggle_layout(self) -> None:
        """Toggle between default (30/70) and swapped (70/30) layout."""
        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)

        self._layout_swapped = not self._layout_swapped

        # Apply layout classes to whichever panel (file or thinking) is visible
        if self.is_thinking_visible():
            secondary_scroll = self.query_one("#agent-thinking-scroll", VerticalScroll)
        else:
            secondary_scroll = self.query_one("#agent-file-scroll", VerticalScroll)

        if self._layout_swapped:
            prompt_scroll.add_class("layout-priority")
            secondary_scroll.add_class("layout-secondary")
        else:
            prompt_scroll.remove_class("layout-priority")
            secondary_scroll.remove_class("layout-secondary")

    def is_thinking_visible(self) -> bool:
        """Check if the thinking panel is currently visible.

        Returns:
            True if the thinking panel is visible, False otherwise.
        """
        return self._force_thinking or self._thinking_auto_shown

    def is_thinking_forced(self) -> bool:
        """Check if the user manually forced the thinking panel via "i" key.

        Returns:
            True if the user toggled thinking on, False if auto-shown or hidden.
        """
        return self._force_thinking

    def is_file_visible(self) -> bool:
        """Check if the file panel is currently visible.

        Returns:
            True if the file panel is visible, False otherwise.
        """
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        return not file_scroll.has_class("hidden")

    def is_layout_swapped(self) -> bool:
        """Check if the layout is currently swapped.

        Returns:
            True if prompt has priority (70/30), False if default (30/70).
        """
        return self._layout_swapped

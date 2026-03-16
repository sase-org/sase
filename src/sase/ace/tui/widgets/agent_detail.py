"""Agent detail widget for the ace TUI."""

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from ..models.agent import Agent
from ._agent_detail_panels import (
    AgentDetailPanelMixin,
    DetailPanelMode,
)
from .file_panel import AgentFilePanel
from .prompt_panel import AgentPromptPanel
from .thinking_panel import AgentThinkingPanel


_ACTIVE_STATUSES = frozenset(
    {"RUNNING", "WAITING", "WAITING INPUT", "PLANNING", "PLAN APPROVED", "QUESTION"}
)


class AgentDetail(AgentDetailPanelMixin, Static):
    """Combined widget with prompt and file panels."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the agent detail view."""
        super().__init__(**kwargs)
        self._layout_swapped: bool = False
        self._panel_mode: DetailPanelMode = DetailPanelMode.AUTO
        self._thinking_auto_shown: bool = False
        self._current_agent: Agent | None = None
        self._has_file_content: bool = False
        self._has_thinking_content: bool = False
        self._file_count: int = 0
        self._file_index: int = 0
        self._trim_visible_lines: int = 0
        self._trim_total_lines: int = 0
        self._trim_is_trimmed: bool = False

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
        # Non-agent entries don't have thinking - just expand prompt
        if not agent.is_agent_entry:
            file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
            prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
            file_scroll.add_class("hidden")
            prompt_scroll.add_class("expanded")
            prompt_scroll.remove_class("layout-priority")
            return

        # Don't auto-show thinking if user chose INFO mode
        if self._panel_mode == DetailPanelMode.INFO:
            return

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
        thinking_panel = self.query_one("#agent-thinking-panel", AgentThinkingPanel)

        # Detect agent change and reset per-agent state, but preserve the
        # user's explicit panel mode choice so that e.g. pressing ']' to show
        # thinking persists across j/k navigation.
        prev_agent = self._current_agent
        self._current_agent = agent
        if prev_agent is not None and prev_agent.identity != agent.identity:
            self._thinking_auto_shown = False
            self._has_file_content = False
            self._has_thinking_content = False
            # Reset from THINKING mode when switching to non-agent entry
            if (
                not agent.is_agent_entry
                and self._panel_mode == DetailPanelMode.THINKING
            ):
                self._panel_mode = DetailPanelMode.AUTO
            if self._panel_mode != DetailPanelMode.THINKING:
                thinking_scroll = self.query_one(
                    "#agent-thinking-scroll", VerticalScroll
                )
                thinking_scroll.add_class("hidden")

        prompt_panel.update_display(agent)
        self._update_panel_indicators()

        # Probe thinking availability in the background so that
        # _has_thinking_content is accurate for panel mode cycling.
        # Skip the probe when the same agent is still selected and we're in
        # INFO mode — the thinking panel is hidden anyway and the cache will
        # be checked when the user toggles to thinking mode.
        same_agent = prev_agent is not None and prev_agent.identity == agent.identity
        if agent.is_agent_entry and not (
            same_agent and self._panel_mode == DetailPanelMode.INFO
        ):
            thinking_panel.update_display(
                agent, stale_threshold_seconds=stale_threshold_seconds
            )

        # INFO mode: only update prompt, hide both secondary panels
        if self._panel_mode == DetailPanelMode.INFO:
            file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
            prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
            file_scroll.add_class("hidden")
            prompt_scroll.add_class("expanded")
            return

        # When thinking panel is visible, keep it showing and just refresh data
        if self._panel_mode == DetailPanelMode.THINKING or self._thinking_auto_shown:
            # Still update file panel in background (for when thinking is toggled off)
            if agent.status in _ACTIVE_STATUSES:
                file_panel.update_display(
                    agent, stale_threshold_seconds=stale_threshold_seconds
                )
                return
            # For completed agents: if thinking was auto-shown (not
            # user-chosen) and the agent has files or a workspace to
            # fetch committed diffs from, fall through to display them.
            # FileVisibilityChanged will handle switching from thinking
            # to file view.
            has_displayable_content = agent.all_files or (
                agent.workspace_num is not None
            )
            if not (self._thinking_auto_shown and has_displayable_content):
                return

        # Bash/python workflow steps don't have files - show thinking as fallback
        if agent.is_workflow_child and agent.step_type in ("bash", "python"):
            self._auto_show_thinking(agent)
            return

        if agent.status in _ACTIVE_STATUSES:
            # Show auto-refreshing file panel for active agents
            # Don't change visibility here - let update_display() handle it
            # via FileVisibilityChanged message after fetching/validating the file
            file_panel.update_display(
                agent, stale_threshold_seconds=stale_threshold_seconds
            )
        else:
            # DONE, FAILED, etc.
            files = agent.all_files
            if files:
                # For .plan agents, default to the plan file (after the diff)
                start = 0
                if agent.role_suffix == ".plan" and len(files) > 1:
                    start = 1
                file_panel.set_file_list(files, start_index=start)
            elif agent.workspace_num is not None:
                # No saved diff file — try fetching committed diff from workspace
                file_panel.update_display(
                    agent, stale_threshold_seconds=stale_threshold_seconds
                )
            else:
                self._auto_show_thinking(agent)

    def update_display_with_hints(self, agent: Agent) -> dict[int, str]:
        """Re-render the prompt panel with file path hints.

        Scans xprompt, prompt, and chat sections for file paths and
        inserts numbered ``[N]`` markers.  Returns the hint mappings so
        the caller can process user selections.

        Args:
            agent: The Agent to display with hints.

        Returns:
            Dict mapping hint numbers to resolved absolute file paths.
        """
        prompt_panel = self.query_one("#agent-prompt-panel", AgentPromptPanel)
        return prompt_panel.update_display_with_hints(agent)

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
        self._panel_mode = DetailPanelMode.AUTO
        self._thinking_auto_shown = False
        self._has_file_content = False
        self._has_thinking_content = False
        self._file_count = 0
        self._file_index = 0
        self._trim_visible_lines = 0
        self._trim_total_lines = 0
        self._trim_is_trimmed = False
        prompt_scroll.border_subtitle = ""
        file_scroll.border_subtitle = ""

    def refresh_current_file(self, agent: Agent) -> None:
        """Force refresh the file for the given agent.

        Args:
            agent: The Agent to refresh file for.
        """
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.refresh_file(agent)

    def cycle_next_file(self) -> None:
        """Cycle to the next file in the file panel."""
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.next_file()

    def cycle_prev_file(self) -> None:
        """Cycle to the previous file in the file panel."""
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.prev_file()

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

        # Recalculate file panel trim after layout change takes effect
        if self.is_file_visible():
            file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
            self.call_after_refresh(file_panel.reset_trim)

    def is_thinking_visible(self) -> bool:
        """Check if the thinking panel is currently visible.

        Returns:
            True if the thinking panel is visible, False otherwise.
        """
        return self._panel_mode == DetailPanelMode.THINKING or self._thinking_auto_shown

    def is_info_mode(self) -> bool:
        """Check if the panel is in info-only mode.

        Returns:
            True if in INFO mode (prompt at 100%), False otherwise.
        """
        return self._panel_mode == DetailPanelMode.INFO

    def is_file_visible(self) -> bool:
        """Check if the file panel is currently visible.

        Returns:
            True if the file panel is visible, False otherwise.
        """
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        return not file_scroll.has_class("hidden")

    def get_editor_file_info(self) -> tuple[str | None, str | None, str]:
        """Get file path, content, and suffix for opening in an editor.

        Returns:
            (file_path, content, suffix) where:
            - file_path is set if a real file can be opened directly
            - content is set if a temp file should be created
            - suffix is the file extension for the temp file
        """
        if self.is_file_visible():
            file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
            return (
                file_panel.get_current_file_path(),
                file_panel.get_current_content(),
                ".diff",
            )
        if self.is_thinking_visible():
            thinking_panel = self.query_one("#agent-thinking-panel", AgentThinkingPanel)
            return (None, thinking_panel.get_thinking_text(), ".md")
        return (None, None, "")

    def expand_file_trim(self) -> None:
        """Expand file content by one page."""
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.expand_by_page()

    def reset_file_trim(self) -> None:
        """Reset file trim to default page size."""
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.reset_trim()

    def show_all_file_lines(self) -> None:
        """Show all file lines (remove trimming)."""
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.show_all_lines()

    def is_file_trimmed(self) -> bool:
        """Check if file content is currently trimmed.

        Returns:
            True if the file content is trimmed, False otherwise.
        """
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        return file_panel.is_trimmed

    def is_layout_swapped(self) -> bool:
        """Check if the layout is currently swapped.

        Returns:
            True if prompt has priority (70/30), False if default (30/70).
        """
        return self._layout_swapped

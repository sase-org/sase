"""Agent detail widget for the ace TUI."""

from enum import Enum
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from sase.llm_provider.registry import get_default_provider_name

from ..models.agent import Agent
from .file_panel import AgentFilePanel, FileListChanged, FileVisibilityChanged
from .prompt_panel import AgentPromptPanel
from .thinking_panel import AgentThinkingPanel, ThinkingVisibilityChanged


_ACTIVE_STATUSES = frozenset(
    {"RUNNING", "WAITING", "WAITING INPUT", "PLANNING", "PLAN APPROVED", "QUESTION"}
)


class _DetailPanelMode(Enum):
    """Three-state cycle for the detail panel view mode."""

    AUTO = "auto"  # File shown (or auto-thinking fallback)
    THINKING = "thinking"  # Thinking panel forced on
    INFO = "info"  # Metadata only, prompt at 100%


def _is_gemini_provider() -> bool:
    """Check if the default LLM provider is Gemini."""
    try:
        return get_default_provider_name() == "gemini"
    except Exception:
        return False


def _default_panel_mode() -> _DetailPanelMode:
    """Get the default panel mode based on the LLM provider.

    Returns INFO for Gemini (hides thinking by default), AUTO otherwise.
    """
    if _is_gemini_provider():
        return _DetailPanelMode.INFO
    return _DetailPanelMode.AUTO


class AgentDetail(Static):
    """Combined widget with prompt and file panels."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the agent detail view."""
        super().__init__(**kwargs)
        self._layout_swapped: bool = False
        self._panel_mode: _DetailPanelMode = _default_panel_mode()
        self._thinking_auto_shown: bool = False
        self._current_agent: Agent | None = None
        self._has_file_content: bool = False
        self._has_thinking_content: bool = False
        self._file_count: int = 0
        self._file_index: int = 0
        self._scroll_thinking_to_bottom: bool = False

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
        # Don't auto-show thinking if user chose INFO mode
        if self._panel_mode == _DetailPanelMode.INFO:
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
        # user's explicit panel mode choice so that e.g. pressing 'i' to show
        # thinking persists across j/k navigation.
        prev_agent = self._current_agent
        self._current_agent = agent
        if prev_agent is not None and prev_agent.identity != agent.identity:
            self._thinking_auto_shown = False
            self._has_file_content = False
            self._has_thinking_content = False
            if self._panel_mode == _DetailPanelMode.THINKING:
                # Keep thinking panel visible; re-enable scroll-to-bottom for
                # Gemini so the new agent's log starts at the latest entry.
                if _is_gemini_provider():
                    self._scroll_thinking_to_bottom = True
            else:
                self._scroll_thinking_to_bottom = False
                thinking_scroll = self.query_one(
                    "#agent-thinking-scroll", VerticalScroll
                )
                thinking_scroll.add_class("hidden")

        prompt_panel.update_display(agent)
        self._update_panel_indicators()

        # Always probe thinking availability in the background so that
        # _has_thinking_content is accurate for panel mode cycling.
        # Without this, done agents with diffs never get their thinking
        # probed and the 'i' key skips the thinking panel entirely.
        thinking_panel.update_display(
            agent, stale_threshold_seconds=stale_threshold_seconds
        )

        # INFO mode: only update prompt, hide both secondary panels
        if self._panel_mode == _DetailPanelMode.INFO:
            file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
            prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
            file_scroll.add_class("hidden")
            prompt_scroll.add_class("expanded")
            return

        # When thinking panel is visible, keep it showing and just refresh data
        if self._panel_mode == _DetailPanelMode.THINKING or self._thinking_auto_shown:
            # Still update file panel in background (for when thinking is toggled off)
            if agent.status in _ACTIVE_STATUSES:
                file_panel.update_display(
                    agent, stale_threshold_seconds=stale_threshold_seconds
                )
                return
            # For completed agents: if thinking was auto-shown (not
            # user-chosen) and the agent has files, fall through to
            # display them.  FileVisibilityChanged will handle
            # switching from thinking to file view.
            if not (self._thinking_auto_shown and agent.all_files):
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
                file_panel.set_file_list(files)
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
        self._panel_mode = _default_panel_mode()
        self._thinking_auto_shown = False
        self._scroll_thinking_to_bottom = False
        self._has_file_content = False
        self._has_thinking_content = False
        self._file_count = 0
        self._file_index = 0
        prompt_scroll.border_subtitle = ""

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

    def on_file_list_changed(self, message: FileListChanged) -> None:
        """Handle file list changes from the file panel.

        Args:
            message: The file list change message.
        """
        self._file_count = message.file_count
        self._file_index = message.file_index
        self._update_panel_indicators()

    def toggle_thinking(self, agent: Agent) -> None:
        """Cycle through available panel modes, skipping unavailable ones.

        Modes without content are skipped:
        - AUTO (file) is skipped when no file content exists
        - THINKING is skipped when no thinking content exists
        - INFO (metadata) is always available

        Args:
            agent: The currently selected agent.
        """
        next_mode = self._next_panel_mode()
        if next_mode is None:
            return
        self._apply_panel_mode(next_mode, agent)
        self._update_panel_indicators()

    def _next_panel_mode(self) -> _DetailPanelMode | None:
        """Compute the next panel mode, skipping unavailable ones.

        Returns:
            The next mode to transition to, or None if there's nothing to
            cycle to.
        """
        # Determine effective current mode (AUTO without file content
        # visually looks like THINKING or INFO, not file view)
        effective = self._panel_mode
        if effective == _DetailPanelMode.AUTO and not self._has_file_content:
            if self._thinking_auto_shown:
                effective = _DetailPanelMode.THINKING
            else:
                effective = _DetailPanelMode.INFO

        # Build list of available modes
        available: list[_DetailPanelMode] = []
        if self._has_file_content:
            available.append(_DetailPanelMode.AUTO)
        if self._has_thinking_content:
            available.append(_DetailPanelMode.THINKING)
        available.append(_DetailPanelMode.INFO)

        if len(available) <= 1:
            return None

        if effective in available:
            idx = available.index(effective)
            return available[(idx + 1) % len(available)]
        return available[0]

    def next_panel_label(self) -> str | None:
        """Get the footer label for what pressing 'i' will do next.

        Returns:
            Label string like "file", "thinking", or "metadata", or None if
            there's nothing to cycle to.
        """
        next_mode = self._next_panel_mode()
        if next_mode is None:
            return None
        labels = {
            _DetailPanelMode.AUTO: "file",
            _DetailPanelMode.THINKING: "thinking",
            _DetailPanelMode.INFO: "collapse",
        }
        return labels[next_mode]

    def _apply_panel_mode(self, mode: _DetailPanelMode, agent: Agent) -> None:
        """Apply visual transition to the given panel mode.

        Args:
            mode: The target panel mode.
            agent: The currently selected agent.
        """
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        thinking_scroll = self.query_one("#agent-thinking-scroll", VerticalScroll)
        thinking_panel = self.query_one("#agent-thinking-panel", AgentThinkingPanel)
        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)

        if mode == _DetailPanelMode.THINKING:
            # Show thinking, hide file
            file_scroll.add_class("hidden")
            thinking_scroll.remove_class("hidden")
            prompt_scroll.remove_class("expanded")

            if self._layout_swapped:
                thinking_scroll.add_class("layout-secondary")
                prompt_scroll.add_class("layout-priority")
            else:
                thinking_scroll.remove_class("layout-secondary")
                prompt_scroll.remove_class("layout-priority")

            self._panel_mode = _DetailPanelMode.THINKING
            self._thinking_auto_shown = False

            # Gemini: scroll to bottom since log has latest entries at bottom
            if _is_gemini_provider():
                self._scroll_thinking_to_bottom = True

            thinking_panel.update_display(agent)

            # Scroll after content is rendered (handles cached content case)
            if self._scroll_thinking_to_bottom:
                self.call_after_refresh(
                    lambda: thinking_scroll.scroll_end(animate=False)
                )

        elif mode == _DetailPanelMode.INFO:
            # Hide both secondary panels, prompt at 100%
            file_scroll.add_class("hidden")
            thinking_scroll.add_class("hidden")
            prompt_scroll.add_class("expanded")
            prompt_scroll.remove_class("layout-priority")

            self._panel_mode = _DetailPanelMode.INFO
            self._thinking_auto_shown = False

        else:
            # AUTO: re-evaluate what to show
            self._panel_mode = _DetailPanelMode.AUTO
            self._thinking_auto_shown = False
            prompt_scroll.remove_class("expanded")
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
        self._has_thinking_content = message.has_thinking
        self._update_panel_indicators()

        if self._panel_mode == _DetailPanelMode.INFO:
            return

        if (
            self._panel_mode != _DetailPanelMode.THINKING
            and not self._thinking_auto_shown
        ):
            return

        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
        thinking_scroll = self.query_one("#agent-thinking-scroll", VerticalScroll)

        if message.has_thinking:
            thinking_scroll.remove_class("hidden")
            prompt_scroll.remove_class("expanded")
            if self._layout_swapped:
                prompt_scroll.add_class("layout-priority")
                thinking_scroll.add_class("layout-secondary")
            # Gemini: scroll to bottom when thinking content first arrives
            if self._scroll_thinking_to_bottom:
                self._scroll_thinking_to_bottom = False
                self.call_after_refresh(
                    lambda: thinking_scroll.scroll_end(animate=False)
                )
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
        self._has_file_content = message.has_file
        self._file_count = message.file_count
        self._file_index = message.file_index
        self._update_panel_indicators()

        # Skip file visibility changes in THINKING or INFO modes
        if self._panel_mode in (_DetailPanelMode.THINKING, _DetailPanelMode.INFO):
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

    def _update_panel_indicators(self) -> None:
        """Update the border subtitle on the prompt panel to show panel state."""
        try:
            prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
        except Exception:
            return

        if self._current_agent is None:
            prompt_scroll.border_subtitle = ""
            return

        text = Text()

        # Files indicator
        file_active = (
            self._panel_mode == _DetailPanelMode.AUTO and self._has_file_content
        )
        if file_active:
            text.append("●", style="bold green")
            text.append(" files", style="bold green")
            if self._file_count > 1:
                text.append(
                    f" [{self._file_index + 1}/{self._file_count}]",
                    style="bold green",
                )
        elif self._has_file_content:
            text.append("●", style="green")
            text.append(" files", style="dim")
            if self._file_count > 1:
                text.append(
                    f" [{self._file_index + 1}/{self._file_count}]",
                    style="dim",
                )
        else:
            text.append("○", style="dim")
            text.append(" files", style="dim")

        text.append("  ")

        # Thinking indicator
        thinking_active = (
            self._panel_mode == _DetailPanelMode.THINKING or self._thinking_auto_shown
        ) and self._has_thinking_content
        if thinking_active and self._panel_mode != _DetailPanelMode.INFO:
            text.append("●", style="bold #af87d7")
            text.append(" thinking", style="bold #af87d7")
        elif self._has_thinking_content:
            text.append("●", style="#af87d7")
            text.append(" thinking", style="dim")
        else:
            text.append("○", style="dim")
            text.append(" thinking", style="dim")

        prompt_scroll.border_subtitle = text

    def is_thinking_visible(self) -> bool:
        """Check if the thinking panel is currently visible.

        Returns:
            True if the thinking panel is visible, False otherwise.
        """
        return (
            self._panel_mode == _DetailPanelMode.THINKING or self._thinking_auto_shown
        )

    def is_info_mode(self) -> bool:
        """Check if the panel is in info-only mode.

        Returns:
            True if in INFO mode (prompt at 100%), False otherwise.
        """
        return self._panel_mode == _DetailPanelMode.INFO

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

    def is_layout_swapped(self) -> bool:
        """Check if the layout is currently swapped.

        Returns:
            True if prompt has priority (70/30), False if default (30/70).
        """
        return self._layout_swapped

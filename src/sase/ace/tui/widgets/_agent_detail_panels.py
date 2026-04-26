"""Panel mode cycling, event handling, and UI indicators for AgentDetail."""

from __future__ import annotations

from enum import Enum

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..models.agent import Agent
from .file_panel import (
    AgentFilePanel,
    FileListChanged,
    FileTrimChanged,
    FileVisibilityChanged,
)
from .thinking_panel import AgentThinkingPanel, ThinkingVisibilityChanged


class DetailPanelMode(Enum):
    """Three-state cycle for the detail panel view mode."""

    AUTO = "auto"  # File shown (prompt expanded when no file)
    THINKING = "thinking"  # Thinking panel forced on
    INFO = "info"  # Metadata only, prompt at 100%


_MODE_LABELS: dict[DetailPanelMode, str] = {
    DetailPanelMode.AUTO: "file",
    DetailPanelMode.THINKING: "thinking",
    DetailPanelMode.INFO: "collapsed",
}


class AgentDetailPanelMixin(Static):
    """Mixin providing panel-mode cycling, event handling, and UI indicators.

    Mixed into ``AgentDetail`` — references to private attributes and
    helper methods (``_expand_prompt_only``, ``update_display``, etc.)
    are provided by that class.  Inherits from ``Static`` so that
    Textual's ``query_one`` / ``call_after_refresh`` are available to
    the type checker.
    """

    # ------------------------------------------------------------------
    # Attribute / method declarations for type-checking.  Actual values
    # are set in AgentDetail.__init__() and AgentDetail itself.
    # ------------------------------------------------------------------
    _panel_mode: DetailPanelMode
    _has_file_content: bool
    _has_thinking_content: bool
    _current_agent: Agent | None
    _layout_swapped: bool
    _file_count: int
    _file_index: int
    _trim_visible_lines: int
    _trim_total_lines: int
    _trim_is_trimmed: bool

    def update_display(
        self, agent: Agent, stale_threshold_seconds: int = 10
    ) -> None: ...

    def _expand_prompt_only(self) -> None:
        """Hide the file panel and expand the prompt panel to fill the space."""
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
        file_scroll.add_class("hidden")
        file_scroll.remove_class("layout-secondary")
        prompt_scroll.add_class("expanded")
        prompt_scroll.remove_class("layout-priority")

    # ------------------------------------------------------------------
    # Panel mode cycling
    # ------------------------------------------------------------------

    def toggle_thinking(self, agent: Agent, *, reverse: bool = False) -> None:
        """Cycle to the next (or previous) panel mode.

        Always cycles through file -> thinking -> none -> file so the
        ``]`` key behaves consistently regardless of content availability.
        The ``[`` key cycles in the opposite direction.

        Args:
            agent: The currently selected agent.
            reverse: If True, cycle in the reverse direction.
        """
        self._apply_panel_mode(self._next_panel_mode(reverse=reverse), agent)
        self._update_panel_indicators()

    def _next_panel_mode(self, *, reverse: bool = False) -> DetailPanelMode:
        """Compute the next panel mode in the fixed cycle.

        For agent entries: AUTO -> THINKING -> INFO -> AUTO.
        For non-agent entries: AUTO -> INFO -> AUTO (no thinking).

        Args:
            reverse: If True, cycle in the reverse direction.

        Returns:
            The next mode to transition to.
        """
        if self._current_agent and self._current_agent.is_agent_entry:
            cycle = [
                DetailPanelMode.AUTO,
                DetailPanelMode.THINKING,
                DetailPanelMode.INFO,
            ]
        else:
            cycle = [
                DetailPanelMode.AUTO,
                DetailPanelMode.INFO,
            ]
        if self._panel_mode not in cycle:
            return cycle[0]
        idx = cycle.index(self._panel_mode)
        step = -1 if reverse else 1
        return cycle[(idx + step) % len(cycle)]

    def next_panel_label(self, *, reverse: bool = False) -> str:
        """Get the footer label for what pressing ``]`` / ``[`` will do next.

        Args:
            reverse: If True, return the label for the reverse direction.

        Returns:
            Label string like "file", "thinking", or "collapsed".
        """
        return _MODE_LABELS[self._next_panel_mode(reverse=reverse)]

    @property
    def panel_mode_label(self) -> str:
        """Get a human-readable label for the current panel mode.

        Returns:
            ``"file"``, ``"thinking"``, or ``"collapsed"``.
        """
        return _MODE_LABELS[self._panel_mode]

    def _apply_panel_mode(self, mode: DetailPanelMode, agent: Agent) -> None:
        """Apply visual transition to the given panel mode.

        Args:
            mode: The target panel mode.
            agent: The currently selected agent.
        """
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        thinking_scroll = self.query_one("#agent-thinking-scroll", VerticalScroll)
        thinking_panel = self.query_one("#agent-thinking-panel", AgentThinkingPanel)
        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)

        if mode == DetailPanelMode.THINKING:
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

            self._panel_mode = DetailPanelMode.THINKING
            thinking_panel.update_display(agent)

        elif mode == DetailPanelMode.INFO:
            # Hide both secondary panels, prompt at 100%
            file_scroll.add_class("hidden")
            thinking_scroll.add_class("hidden")
            prompt_scroll.add_class("expanded")
            prompt_scroll.remove_class("layout-priority")

            self._panel_mode = DetailPanelMode.INFO

        else:
            # AUTO: re-evaluate what to show
            self._panel_mode = DetailPanelMode.AUTO
            prompt_scroll.remove_class("expanded")
            thinking_scroll.add_class("hidden")
            file_scroll.remove_class("hidden")
            self.update_display(agent)

            # If file panel has no content, expand prompt instead of
            # leaving an empty "No changes detected" panel visible.
            if not self._has_file_content:
                self._expand_prompt_only()
            else:
                file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
                self.call_after_refresh(file_panel.reset_trim)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_file_list_changed(self, message: FileListChanged) -> None:
        """Handle file list changes from the file panel.

        Args:
            message: The file list change message.
        """
        self._file_count = message.file_count
        self._file_index = message.file_index
        self._update_panel_indicators()

    def on_file_trim_changed(self, message: FileTrimChanged) -> None:
        """Handle file trim state changes from the file panel.

        Args:
            message: The trim change message.
        """
        self._trim_visible_lines = message.visible_lines
        self._trim_total_lines = message.total_lines
        self._trim_is_trimmed = message.is_trimmed
        self._update_file_scroll_subtitle()

    def on_thinking_visibility_changed(
        self, message: ThinkingVisibilityChanged
    ) -> None:
        """Handle thinking panel visibility changes.

        Args:
            message: The visibility change message.
        """
        self._has_thinking_content = message.has_thinking
        self._update_panel_indicators()

        if self._panel_mode != DetailPanelMode.THINKING:
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
        if self._panel_mode in (DetailPanelMode.THINKING, DetailPanelMode.INFO):
            return

        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)

        if message.has_file:
            was_hidden = file_scroll.has_class("hidden")
            # Show file panel
            file_scroll.remove_class("hidden")
            prompt_scroll.remove_class("expanded")
            # Restore layout preference if swapped
            if self._layout_swapped:
                prompt_scroll.add_class("layout-priority")
                file_scroll.add_class("layout-secondary")
            if was_hidden:
                file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
                self.call_after_refresh(file_panel.reset_trim)
        else:
            self._expand_prompt_only()

    # ------------------------------------------------------------------
    # UI indicators
    # ------------------------------------------------------------------

    def _update_file_scroll_subtitle(self) -> None:
        """Update the border subtitle on the file scroll panel to show line counts."""
        try:
            file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        except Exception:
            return

        if self._trim_total_lines == 0:
            file_scroll.border_subtitle = ""
        elif self._trim_is_trimmed:
            file_scroll.border_subtitle = Text(
                f"Lines 1-{self._trim_visible_lines} of {self._trim_total_lines}",
                style="dim #87D7FF",
            )
        else:
            file_scroll.border_subtitle = Text(
                f"{self._trim_total_lines} lines",
                style="dim #5FAFAF",
            )

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
            self._panel_mode == DetailPanelMode.AUTO and self._has_file_content
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

        # Thinking indicator - only for agent entries
        if self._current_agent and self._current_agent.is_agent_entry:
            text.append("  ")

            thinking_active = (
                self._panel_mode == DetailPanelMode.THINKING
                and self._has_thinking_content
            )
            if thinking_active and self._panel_mode != DetailPanelMode.INFO:
                text.append("●", style="bold #af87d7")
                text.append(" thinking", style="bold #af87d7")
            elif self._has_thinking_content:
                text.append("●", style="#af87d7")
                text.append(" thinking", style="dim")
            else:
                text.append("○", style="dim")
                text.append(" thinking", style="dim")

        prompt_scroll.border_subtitle = text

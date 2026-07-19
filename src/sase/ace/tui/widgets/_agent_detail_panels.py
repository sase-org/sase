"""Panel mode cycling, event handling, and UI indicators for AgentDetail."""

from __future__ import annotations

from enum import Enum

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..tools import supports_slow_tool_sources
from ..models.agent import Agent
from .file_panel import (
    AgentFilePanel,
    FileListChanged,
    FileLineCountChanged,
    FileVisibilityChanged,
)
from .tools_panel import AgentToolsPanel, ToolsVisibilityChanged


class DetailPanelMode(Enum):
    """Three-state cycle for the detail panel view mode."""

    AUTO = "auto"  # File shown (prompt expanded when no file)
    TOOLS = "tools"  # Tools panel forced on
    INFO = "info"  # Metadata only, prompt at 100%


_MODE_LABELS: dict[DetailPanelMode, str] = {
    DetailPanelMode.AUTO: "file",
    DetailPanelMode.TOOLS: "tools",
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
    _has_tools_content: bool
    _current_agent: Agent | None
    _layout_swapped: bool
    _file_count: int
    _file_index: int
    _file_visible_lines: int
    _file_total_lines: int
    _file_content_capped: bool

    def _active_metadata_scroll(self) -> VerticalScroll:
        raise NotImplementedError

    def update_display(
        self, agent: Agent, stale_threshold_seconds: int = 10
    ) -> None: ...

    def _expand_prompt_only(self) -> None:
        """Hide the file panel and expand the prompt panel to fill the space."""
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        prompt_scroll = self._active_metadata_scroll()
        file_scroll.add_class("hidden")
        file_scroll.remove_class("layout-secondary")
        prompt_scroll.add_class("expanded")
        prompt_scroll.remove_class("layout-priority")

    # ------------------------------------------------------------------
    # Panel mode cycling
    # ------------------------------------------------------------------

    def toggle_tools(self, agent: Agent, *, reverse: bool = False) -> None:
        """Cycle to the next (or previous) panel mode.

        Always cycles through file -> tools -> none -> file so the
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

        For entries with tool sources: AUTO -> TOOLS -> INFO -> AUTO.
        For other entries: AUTO -> INFO -> AUTO (no tools).

        Args:
            reverse: If True, cycle in the reverse direction.

        Returns:
            The next mode to transition to.
        """
        if self._current_agent and supports_slow_tool_sources(self._current_agent):
            cycle = [
                DetailPanelMode.AUTO,
                DetailPanelMode.TOOLS,
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
            Label string like "file", "tools", or "collapsed".
        """
        return _MODE_LABELS[self._next_panel_mode(reverse=reverse)]

    @property
    def panel_mode_label(self) -> str:
        """Get a human-readable label for the current panel mode.

        Returns:
            ``"file"``, ``"tools"``, or ``"collapsed"``.
        """
        return _MODE_LABELS[self._panel_mode]

    def _apply_panel_mode(self, mode: DetailPanelMode, agent: Agent) -> None:
        """Apply visual transition to the given panel mode.

        Args:
            mode: The target panel mode.
            agent: The currently selected agent.
        """
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        tools_scroll = self.query_one("#agent-tools-scroll", VerticalScroll)
        tools_panel = self.query_one("#agent-tools-panel", AgentToolsPanel)
        prompt_scroll = self._active_metadata_scroll()

        if mode == DetailPanelMode.TOOLS:
            # Show tools, hide file
            file_scroll.add_class("hidden")
            tools_scroll.remove_class("hidden")
            prompt_scroll.remove_class("expanded")

            if self._layout_swapped:
                tools_scroll.add_class("layout-secondary")
                prompt_scroll.add_class("layout-priority")
            else:
                tools_scroll.remove_class("layout-secondary")
                prompt_scroll.remove_class("layout-priority")

            self._panel_mode = DetailPanelMode.TOOLS
            tools_panel.update_display(agent)

        elif mode == DetailPanelMode.INFO:
            # Hide both secondary panels, prompt at 100%
            file_scroll.add_class("hidden")
            tools_scroll.add_class("hidden")
            prompt_scroll.add_class("expanded")
            prompt_scroll.remove_class("layout-priority")

            self._panel_mode = DetailPanelMode.INFO

        else:
            # AUTO: re-evaluate what to show
            self._panel_mode = DetailPanelMode.AUTO
            prompt_scroll.remove_class("expanded")
            tools_scroll.add_class("hidden")
            file_scroll.remove_class("hidden")
            # Invalidate file_panel state so the next dispatch skips the
            # same-agent fast paths in both `_update_display_body` and
            # `set_file_list` and forces a fresh render. Required because the
            # panel may have been hidden across a navigation that bypassed it,
            # leaving its visible content out of sync with the new agent.
            file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
            file_panel._current_agent = None
            file_panel._file_list = []
            self.update_display(agent)

            # If file panel has no content, expand prompt instead of
            # leaving an empty "No changes detected" panel visible.
            if not self._has_file_content:
                self._expand_prompt_only()

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
        self._update_file_scroll_title()

    def on_file_line_count_changed(self, message: FileLineCountChanged) -> None:
        """Handle file line-count changes from the file panel.

        Args:
            message: The line-count change message.
        """
        self._file_visible_lines = message.visible_lines
        self._file_total_lines = message.total_lines
        self._file_content_capped = message.capped
        self._update_file_scroll_subtitle()

    def on_tools_visibility_changed(self, message: ToolsVisibilityChanged) -> None:
        """Handle tools panel visibility changes.

        Args:
            message: The visibility change message.
        """
        self._has_tools_content = message.has_tools
        self._update_panel_indicators()

        if self._panel_mode != DetailPanelMode.TOOLS:
            return

        prompt_scroll = self._active_metadata_scroll()
        tools_scroll = self.query_one("#agent-tools-scroll", VerticalScroll)

        tools_scroll.remove_class("hidden")
        prompt_scroll.remove_class("expanded")
        if self._layout_swapped:
            prompt_scroll.add_class("layout-priority")
            tools_scroll.add_class("layout-secondary")

    def on_file_visibility_changed(self, message: FileVisibilityChanged) -> None:
        """Handle file panel visibility changes.

        Args:
            message: The visibility change message.
        """
        self._has_file_content = message.has_file
        self._file_count = message.file_count
        self._file_index = message.file_index
        self._update_panel_indicators()
        self._update_file_scroll_title()

        # Skip file visibility changes in TOOLS or INFO modes
        if self._panel_mode in (DetailPanelMode.TOOLS, DetailPanelMode.INFO):
            return

        prompt_scroll = self._active_metadata_scroll()
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)

        if message.has_file:
            # Show file panel
            file_scroll.remove_class("hidden")
            prompt_scroll.remove_class("expanded")
            # Restore layout preference if swapped
            if self._layout_swapped:
                prompt_scroll.add_class("layout-priority")
                file_scroll.add_class("layout-secondary")
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

        if self._file_total_lines == 0:
            file_scroll.border_subtitle = ""
        elif self._file_content_capped:
            file_scroll.border_subtitle = Text(
                f"1-{self._file_visible_lines} of {self._file_total_lines} lines (E: editor)",
                style="dim #87D7FF",
            )
        else:
            file_scroll.border_subtitle = Text(
                f"{self._file_total_lines} lines",
                style="dim #5FAFAF",
            )

    def _current_file_source_label(self) -> str | None:
        try:
            file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        except Exception:
            return None
        return file_panel.current_source_label()

    def _update_file_scroll_title(self) -> None:
        """Update the file panel border title with the current page source."""
        try:
            file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        except Exception:
            return
        label = self._current_file_source_label()
        if label:
            file_scroll.border_title = Text(label, style="bold green")
        else:
            file_scroll.border_title = ""

    def _update_panel_indicators(self) -> None:
        """Update the border subtitle on the prompt panel to show panel state."""
        try:
            prompt_scroll = self._active_metadata_scroll()
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
            source_label = self._current_file_source_label()
            if source_label:
                text.append(f" · {source_label}", style="bold green")
        elif self._has_file_content:
            text.append("●", style="green")
            text.append(" files", style="dim")
            if self._file_count > 1:
                text.append(
                    f" [{self._file_index + 1}/{self._file_count}]",
                    style="dim",
                )
            source_label = self._current_file_source_label()
            if source_label:
                text.append(f" · {source_label}", style="dim")
        else:
            text.append("○", style="dim")
            text.append(" files", style="dim")

        # Tools indicator - only for entries with tool sources
        if self._current_agent and supports_slow_tool_sources(self._current_agent):
            text.append("  ")

            tools_active = (
                self._panel_mode == DetailPanelMode.TOOLS and self._has_tools_content
            )
            if tools_active and self._panel_mode != DetailPanelMode.INFO:
                text.append("●", style="bold #87D7FF")
                text.append(" tools", style="bold #87D7FF")
            elif self._has_tools_content:
                text.append("●", style="#87D7FF")
                text.append(" tools", style="dim")
            else:
                text.append("○", style="dim")
                text.append(" tools", style="dim")

        prompt_scroll.border_subtitle = text

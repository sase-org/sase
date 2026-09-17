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


class DetailLayoutMode(Enum):
    """Existing vertical detail-layout proportions."""

    SECONDARY_LARGER = "secondary_larger"  # Metadata 30% / File or Tools 70%
    METADATA_LARGER = "metadata_larger"  # Metadata 70% / File or Tools 30%


_MODE_LABELS: dict[DetailPanelMode, str] = {
    DetailPanelMode.AUTO: "file",
    DetailPanelMode.TOOLS: "tools",
    DetailPanelMode.INFO: "none",
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
        tools_scroll = self.query_one("#agent-tools-scroll", VerticalScroll)
        prompt_scroll = self._active_metadata_scroll()
        file_scroll.add_class("hidden")
        tools_scroll.add_class("hidden")
        file_scroll.remove_class("layout-secondary")
        tools_scroll.remove_class("layout-secondary")
        prompt_scroll.add_class("expanded")
        prompt_scroll.remove_class("layout-priority")

    @property
    def panel_mode_label(self) -> str:
        """Get a human-readable label for the current panel mode.

        Returns:
            ``"file"``, ``"tools"``, or ``"none"``.
        """
        return _MODE_LABELS[self._panel_mode]

    @property
    def panel_mode(self) -> DetailPanelMode:
        """Return the current detail panel mode."""
        return self._panel_mode

    @property
    def detail_layout_mode(self) -> DetailLayoutMode:
        """Return the saved detail layout preference."""
        if self._layout_swapped:
            return DetailLayoutMode.METADATA_LARGER
        return DetailLayoutMode.SECONDARY_LARGER

    def set_detail_layout(self, layout: DetailLayoutMode) -> bool:
        """Set the saved layout and apply it to the visible secondary panel.

        Returns True when the saved preference changed.
        """
        old = self.detail_layout_mode
        self._layout_swapped = layout is DetailLayoutMode.METADATA_LARGER
        self._apply_detail_layout_classes()
        return old is not layout

    def toggle_layout(self) -> None:
        """Toggle between default (30/70) and swapped (70/30) layout."""
        target = (
            DetailLayoutMode.SECONDARY_LARGER
            if self._layout_swapped
            else DetailLayoutMode.METADATA_LARGER
        )
        self.set_detail_layout(target)

    def _apply_detail_layout_classes(self) -> None:
        """Apply the saved layout to the currently visible secondary panel."""
        prompt_scroll = self._active_metadata_scroll()
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        tools_scroll = self.query_one("#agent-tools-scroll", VerticalScroll)
        file_scroll.remove_class("layout-secondary")
        tools_scroll.remove_class("layout-secondary")

        if self._panel_mode == DetailPanelMode.INFO:
            prompt_scroll.remove_class("layout-priority")
            return

        secondary_scroll = None
        if self._panel_mode == DetailPanelMode.TOOLS and not tools_scroll.has_class(
            "hidden"
        ):
            secondary_scroll = tools_scroll
        elif self._panel_mode == DetailPanelMode.AUTO and not file_scroll.has_class(
            "hidden"
        ):
            secondary_scroll = file_scroll

        if secondary_scroll is None:
            prompt_scroll.remove_class("layout-priority")
            return

        if self._layout_swapped:
            prompt_scroll.add_class("layout-priority")
            secondary_scroll.add_class("layout-secondary")
        else:
            prompt_scroll.remove_class("layout-priority")

    def set_panel_mode(
        self,
        mode: DetailPanelMode,
        agent: Agent,
        *,
        attempt_number: int | None = None,
    ) -> bool:
        """Apply a detail mode explicitly.

        Same-mode selections are a no-op only when the rendered detail already
        belongs to the selected row and attempt.
        """
        if (
            mode is self._panel_mode
            and self._current_agent is not None
            and self._current_agent.identity == agent.identity
            and getattr(self, "_current_attempt_number", None) == attempt_number
        ):
            return False
        self._apply_panel_mode(mode, agent)
        self._update_panel_indicators()
        return True

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
            file_scroll.remove_class("layout-secondary")
            tools_scroll.remove_class("hidden")
            prompt_scroll.remove_class("expanded")

            self._panel_mode = DetailPanelMode.TOOLS
            self._apply_detail_layout_classes()
            tools_panel.update_display(agent)

        elif mode == DetailPanelMode.INFO:
            # Hide both secondary panels, prompt at 100%
            file_scroll.add_class("hidden")
            tools_scroll.add_class("hidden")
            file_scroll.remove_class("layout-secondary")
            tools_scroll.remove_class("layout-secondary")
            prompt_scroll.add_class("expanded")
            prompt_scroll.remove_class("layout-priority")

            self._panel_mode = DetailPanelMode.INFO

        else:
            # AUTO: re-evaluate what to show
            self._panel_mode = DetailPanelMode.AUTO
            prompt_scroll.remove_class("expanded")
            tools_scroll.add_class("hidden")
            tools_scroll.remove_class("layout-secondary")
            file_scroll.remove_class("hidden")
            self._apply_detail_layout_classes()
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
        self._apply_detail_layout_classes()

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
            self._apply_detail_layout_classes()
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

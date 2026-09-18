"""Panel mode cycling, event handling, and UI indicators for AgentDetail."""

from __future__ import annotations

from enum import Enum
from typing import Final

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..llm_calls import supports_slow_tool_sources
from ..models.agent import Agent
from .file_panel import (
    AgentFilePanel,
    FileListChanged,
    FileLineCountChanged,
    FileVisibilityChanged,
)
from .llm_calls_panel import AgentLLMCallsPanel, LLMCallsVisibilityChanged


class DetailPanelMode(Enum):
    """Secondary content selection for the detail panel."""

    AUTO = "auto"  # File shown (prompt expanded when no file)
    LLM_CALLS = "llm_calls"  # LLM Calls panel forced on
    INFO = "info"  # Compatibility alias for metadata-only layout


class DetailLayoutMode(Enum):
    """Saved vertical detail-layout proportions."""

    METADATA_ONLY = "metadata_only"  # Metadata 100% / File/LLM Calls 0%
    METADATA_LARGER = "metadata_larger"  # Metadata 70% / File/LLM Calls 30%
    EQUAL = "equal"  # Metadata 50% / File/LLM Calls 50%
    SECONDARY_LARGER = "secondary_larger"  # Metadata 30% / File/LLM Calls 70%
    SECONDARY_ONLY = "secondary_only"  # Metadata 0% / File/LLM Calls 100%


DETAIL_LAYOUT_CYCLE: Final[tuple[DetailLayoutMode, ...]] = (
    DetailLayoutMode.METADATA_LARGER,
    DetailLayoutMode.EQUAL,
    DetailLayoutMode.SECONDARY_LARGER,
)


_MODE_LABELS: dict[DetailPanelMode, str] = {
    DetailPanelMode.AUTO: "file",
    DetailPanelMode.LLM_CALLS: "llm calls",
    DetailPanelMode.INFO: "none",
}


def next_detail_layout_mode(
    layout: DetailLayoutMode, *, direction: int = 1
) -> DetailLayoutMode:
    """Return the next saved detail layout in the canonical circular order."""
    if layout not in DETAIL_LAYOUT_CYCLE:
        return DetailLayoutMode.EQUAL
    index = DETAIL_LAYOUT_CYCLE.index(layout)
    return DETAIL_LAYOUT_CYCLE[(index + direction) % len(DETAIL_LAYOUT_CYCLE)]


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
    _has_llm_calls_content: bool
    _current_agent: Agent | None
    _detail_layout_mode: DetailLayoutMode
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

    def is_info_mode(self) -> bool:
        raise NotImplementedError

    def is_file_visible(self) -> bool:
        raise NotImplementedError

    def is_llm_calls_visible(self) -> bool:
        raise NotImplementedError

    def _expand_prompt_only(self) -> None:
        """Hide the file panel and expand the prompt panel to fill the space."""
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        llm_calls_scroll = self.query_one("#agent-llm-calls-scroll", VerticalScroll)
        prompt_scroll = self._active_metadata_scroll()
        self._show_active_metadata_scroll(prompt_scroll)
        file_scroll.add_class("hidden")
        llm_calls_scroll.add_class("hidden")
        self._clear_detail_layout_classes()
        prompt_scroll.add_class("expanded")

    @property
    def panel_mode_label(self) -> str:
        """Get a human-readable label for the current panel mode.

        Returns:
            ``"file"``, ``"llm calls"``, or ``"none"``.
        """
        if self.is_info_mode():
            return _MODE_LABELS[DetailPanelMode.INFO]
        if self.is_llm_calls_visible():
            return _MODE_LABELS[DetailPanelMode.LLM_CALLS]
        if self.is_file_visible():
            return _MODE_LABELS[DetailPanelMode.AUTO]
        return _MODE_LABELS[self._selected_secondary_mode()]

    @property
    def panel_mode(self) -> DetailPanelMode:
        """Return the current detail panel mode."""
        return self._panel_mode

    @property
    def detail_layout_mode(self) -> DetailLayoutMode:
        """Return the saved detail layout preference."""
        return self._detail_layout_mode

    def set_detail_layout(self, layout: DetailLayoutMode) -> bool:
        """Set the saved layout and apply it to the visible secondary panel.

        Returns True when the saved preference changed.
        """
        old = self.detail_layout_mode
        self._detail_layout_mode = layout
        self._apply_detail_layout_classes()
        return old is not layout

    def cycle_detail_layout(self, *, direction: int = 1) -> bool:
        """Cycle the saved layout in the canonical order."""
        return self.set_detail_layout(
            next_detail_layout_mode(self._detail_layout_mode, direction=direction)
        )

    def toggle_layout(self) -> None:
        """Retained compatibility alias for cycling to the next layout."""
        self.cycle_detail_layout(direction=1)

    def _clear_detail_layout_classes(self) -> None:
        """Remove all saved-layout sizing classes from detail scroll containers."""
        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
        search_scroll = self.query_one("#agent-search-scroll", VerticalScroll)
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        llm_calls_scroll = self.query_one("#agent-llm-calls-scroll", VerticalScroll)
        for scroll in (prompt_scroll, search_scroll, file_scroll, llm_calls_scroll):
            scroll.remove_class("expanded")
            scroll.remove_class("layout-priority")
            scroll.remove_class("layout-secondary")
            scroll.remove_class("layout-equal")

    def _show_active_metadata_scroll(self, active_scroll: VerticalScroll) -> None:
        """Show the native metadata scroll or its active search overlay."""
        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
        search_scroll = self.query_one("#agent-search-scroll", VerticalScroll)
        if active_scroll is search_scroll:
            prompt_scroll.add_class("hidden")
            search_scroll.remove_class("hidden")
        else:
            prompt_scroll.remove_class("hidden")
            search_scroll.add_class("hidden")

    def _hide_metadata_scrolls(self) -> None:
        """Hide both metadata scroll variants."""
        self.query_one("#agent-prompt-scroll", VerticalScroll).add_class("hidden")
        self.query_one("#agent-search-scroll", VerticalScroll).add_class("hidden")

    def _selected_secondary_mode(self) -> DetailPanelMode:
        """Return the selected secondary content mode, normalizing legacy INFO."""
        if self._panel_mode is DetailPanelMode.LLM_CALLS:
            return DetailPanelMode.LLM_CALLS
        return DetailPanelMode.AUTO

    def _selected_secondary_scroll(self) -> VerticalScroll:
        """Return the File or LLM Calls scroll for the selected secondary mode."""
        if self._selected_secondary_mode() is DetailPanelMode.LLM_CALLS:
            return self.query_one("#agent-llm-calls-scroll", VerticalScroll)
        return self.query_one("#agent-file-scroll", VerticalScroll)

    def _hide_unselected_secondary_scroll(self) -> None:
        """Hide the secondary scroll that is not currently selected."""
        selected = self._selected_secondary_scroll()
        for selector in ("#agent-file-scroll", "#agent-llm-calls-scroll"):
            scroll = self.query_one(selector, VerticalScroll)
            if scroll is not selected:
                scroll.add_class("hidden")

    def selected_secondary_available(self) -> bool:
        """Return whether the selected secondary panel has content to show."""
        if self._selected_secondary_mode() is DetailPanelMode.LLM_CALLS:
            return self._has_llm_calls_content
        return self._has_file_content

    def _apply_detail_layout_classes(self) -> None:
        """Apply the saved layout to the selected secondary panel."""
        prompt_scroll = self._active_metadata_scroll()
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        llm_calls_scroll = self.query_one("#agent-llm-calls-scroll", VerticalScroll)
        self._clear_detail_layout_classes()
        self._hide_unselected_secondary_scroll()

        secondary_scroll = self._selected_secondary_scroll()
        secondary_available = self.selected_secondary_available()
        if (
            self._detail_layout_mode is DetailLayoutMode.METADATA_ONLY
            or not secondary_available
        ):
            self._show_active_metadata_scroll(prompt_scroll)
            file_scroll.add_class("hidden")
            llm_calls_scroll.add_class("hidden")
            prompt_scroll.add_class("expanded")
            return

        if self._detail_layout_mode is DetailLayoutMode.SECONDARY_ONLY:
            self._hide_metadata_scrolls()
            secondary_scroll.remove_class("hidden")
            secondary_scroll.add_class("expanded")
            return

        self._show_active_metadata_scroll(prompt_scroll)
        secondary_scroll.remove_class("hidden")
        if self._detail_layout_mode is DetailLayoutMode.METADATA_LARGER:
            prompt_scroll.add_class("layout-priority")
            secondary_scroll.add_class("layout-secondary")
        elif self._detail_layout_mode is DetailLayoutMode.EQUAL:
            prompt_scroll.add_class("layout-equal")
            secondary_scroll.add_class("layout-equal")

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
            mode is not DetailPanelMode.INFO
            and mode is self._panel_mode
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
        llm_calls_scroll = self.query_one("#agent-llm-calls-scroll", VerticalScroll)
        llm_calls_panel = self.query_one("#agent-llm-calls-panel", AgentLLMCallsPanel)

        if mode == DetailPanelMode.LLM_CALLS:
            self._panel_mode = DetailPanelMode.LLM_CALLS
            llm_calls_panel.update_display(agent)
            file_scroll.add_class("hidden")
            self._apply_detail_layout_classes()

        elif mode == DetailPanelMode.INFO:
            self._detail_layout_mode = DetailLayoutMode.METADATA_ONLY
            if self._panel_mode is DetailPanelMode.INFO:
                self._panel_mode = DetailPanelMode.AUTO
            self._apply_detail_layout_classes()

        else:
            # AUTO: re-evaluate what to show
            self._panel_mode = DetailPanelMode.AUTO
            llm_calls_scroll.add_class("hidden")
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
            else:
                self._apply_detail_layout_classes()

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

    def on_llm_calls_visibility_changed(
        self, message: LLMCallsVisibilityChanged
    ) -> None:
        """Handle LLM Calls panel visibility changes.

        Args:
            message: The visibility change message.
        """
        self._has_llm_calls_content = message.has_llm_calls
        self._update_panel_indicators()

        if self._panel_mode != DetailPanelMode.LLM_CALLS:
            return
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

        # Skip file visibility changes while LLM Calls is the selected secondary.
        if self._panel_mode == DetailPanelMode.LLM_CALLS:
            return

        if message.has_file:
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
        file_active = self.is_file_visible()
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

        # LLM Calls indicator - only for entries with tool sources.
        if self._current_agent and supports_slow_tool_sources(self._current_agent):
            text.append("  ")

            llm_calls_active = (
                self.is_llm_calls_visible() and self._has_llm_calls_content
            )
            if llm_calls_active:
                text.append("●", style="bold #87D7FF")
                text.append(" llm calls", style="bold #87D7FF")
            elif self._has_llm_calls_content:
                text.append("●", style="#87D7FF")
                text.append(" llm calls", style="dim")
            else:
                text.append("○", style="dim")
                text.append(" llm calls", style="dim")

        prompt_scroll.border_subtitle = text

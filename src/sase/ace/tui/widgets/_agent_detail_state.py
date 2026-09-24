"""Empty/tribe states, file navigation, and visibility queries for AgentDetail."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import VerticalScroll
from textual.css.query import NoMatches

from ..util.trace import tui_trace
from ._agent_detail_helpers import agent_prompt_panel_type
from ._agent_detail_panels import AgentDetailPanelMixin, DetailPanelMode
from .file_panel import AgentFilePanel
from .file_panel._messages import LinkedDeltasRefreshed
from .llm_calls_panel import AgentLLMCallsPanel, ToolDetailLevel

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.agent_tribe_summary import (
        AgentTribeSummarySnapshot,
        TribePanelIdentity,
    )


class AgentDetailStateMixin(AgentDetailPanelMixin):
    """Mixin for AgentDetail secondary states and visibility queries.

    Covers the empty and tribe-summary documents, file-panel navigation,
    LLM Calls detail levels, visibility predicates, editor export, and the
    attempt-history view mode. Mixed into ``AgentDetail``. Extends
    ``AgentDetailPanelMixin`` so layout helpers and ``update_display``
    resolve through inheritance instead of stubs.
    """

    # ------------------------------------------------------------------
    # Attribute / method declarations for type-checking. Actual values
    # are set in AgentDetail.__init__() and AgentDetail itself.
    # ------------------------------------------------------------------
    _current_agent: Agent | None
    _current_tribe_identity: TribePanelIdentity | None
    _current_attempt_number: int | None
    _attempt_view_mode: str
    _agent_detail_generation: int
    _has_file_content: bool
    _has_llm_calls_content: bool
    _file_count: int
    _file_index: int
    _file_visible_lines: int
    _file_total_lines: int
    _file_content_capped: bool
    _panel_mode: DetailPanelMode

    @property
    def metadata_identity(self) -> object | None:
        raise NotImplementedError

    def _publish_metadata_identity_change(self, previous: object | None) -> None:
        raise NotImplementedError

    def show_empty(self) -> None:
        """Show empty state for all panels."""
        if bool(getattr(self, "decks_enabled", False)):
            previous_identity = self.metadata_identity
            self._deck_show_empty()  # type: ignore[attr-defined]
            self._publish_metadata_identity_change(previous_identity)
            self._sync_header_visibility()
            return
        previous_identity = self.metadata_identity
        self._agent_detail_generation += 1
        self._current_agent = None
        self._current_tribe_identity = None
        self._current_attempt_number = None
        prompt_panel = self.query_one("#agent-prompt-panel", agent_prompt_panel_type())
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        llm_calls_panel = self.query_one("#agent-llm-calls-panel", AgentLLMCallsPanel)

        prompt_panel.show_empty()
        file_panel.show_empty()
        llm_calls_panel.show_empty()

        # Hide file and LLM Calls panels when no agent is selected
        prompt_scroll = self._active_metadata_scroll()
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        llm_calls_scroll = self.query_one("#agent-llm-calls-scroll", VerticalScroll)
        file_scroll.add_class("hidden")
        llm_calls_scroll.add_class("hidden")
        self._clear_detail_layout_classes()
        prompt_scroll.add_class("expanded")
        self._panel_mode = DetailPanelMode.AUTO
        self._has_file_content = False
        self._has_llm_calls_content = False
        self._file_count = 0
        self._file_index = 0
        self._file_visible_lines = 0
        self._file_total_lines = 0
        self._file_content_capped = False
        prompt_scroll.border_subtitle = ""
        file_scroll.border_title = ""
        file_scroll.border_subtitle = ""
        self._publish_metadata_identity_change(previous_identity)
        self._sync_header_visibility()

    def show_tribe_summary(
        self,
        snapshot: AgentTribeSummarySnapshot,
        *,
        cheap: bool = False,
    ) -> None:
        """Show a tribe document on the regular fold-aware prompt surface."""
        if bool(getattr(self, "decks_enabled", False)):
            previous_identity = self.metadata_identity
            self._deck_show_tribe_summary(snapshot, cheap=cheap)  # type: ignore[attr-defined]
            self._publish_metadata_identity_change(previous_identity)
            self._sync_header_visibility()
            return
        previous_identity = self.metadata_identity
        self._agent_detail_generation += 1
        self._current_agent = None
        self._current_tribe_identity = snapshot.container_identity
        self._current_attempt_number = None
        prompt_panel = self.query_one("#agent-prompt-panel", agent_prompt_panel_type())
        prompt_panel.update_tribe_display(snapshot, cheap=cheap)
        prompt_scroll = self._active_metadata_scroll()
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        llm_calls_scroll = self.query_one("#agent-llm-calls-scroll", VerticalScroll)
        file_scroll.add_class("hidden")
        llm_calls_scroll.add_class("hidden")
        self._clear_detail_layout_classes()
        prompt_scroll.add_class("expanded")
        self._has_file_content = False
        self._has_llm_calls_content = False
        prompt_scroll.border_subtitle = ""
        self._publish_metadata_identity_change(previous_identity)
        self._sync_header_visibility()

    def refresh_current_file(self, agent: Agent) -> None:
        """Force refresh the file for the given agent.

        Args:
            agent: The Agent to refresh file for.
        """
        with tui_trace("agent_detail.refresh_current_file"):
            if bool(getattr(self, "decks_enabled", False)):
                try:
                    panel = self.deck_area.focused_panel()  # type: ignore[attr-defined]
                    panel.file_view.refresh_file(agent)
                except Exception:
                    pass
                return
            file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
            file_panel.refresh_file(agent)

    def cycle_next_file(self) -> None:
        """Cycle to the next file in the file panel."""
        if bool(getattr(self, "decks_enabled", False)):
            try:
                self.deck_area.focused_panel().file_view.next_file()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.next_file()

    def cycle_prev_file(self) -> None:
        """Cycle to the previous file in the file panel."""
        if bool(getattr(self, "decks_enabled", False)):
            try:
                self.deck_area.focused_panel().file_view.prev_file()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.prev_file()

    def on_linked_deltas_refreshed(self, message: LinkedDeltasRefreshed) -> None:
        """Refresh file-panel linked pages after the prompt worker updates cache."""
        if (
            self._current_agent is None
            or self._current_agent.identity != message.agent_identity
        ):
            return
        if bool(getattr(self, "decks_enabled", False)):
            try:
                from .decks.model import DeckId as _DeckId

                for panel in self.deck_area.panels_showing(_DeckId.FILES):  # type: ignore[attr-defined]
                    panel.file_view.reconcile_linked_pages(self._current_agent)
            except Exception:
                pass
            message.stop()
            return
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        file_panel.reconcile_linked_pages(self._current_agent)
        message.stop()

    def is_llm_calls_visible(self) -> bool:
        """Check if the LLM Calls panel is currently visible.

        Returns:
            True if the LLM Calls panel is visible, False otherwise.
        """
        if bool(getattr(self, "decks_enabled", False)):
            if self._current_agent is None:
                return False
            try:
                from .decks.model import DeckId as _DeckId

                for panel in self.deck_area.visible_panels():  # type: ignore[attr-defined]
                    if panel.deck is _DeckId.TOOLS and not panel._deck_is_empty(
                        _DeckId.TOOLS
                    ):
                        return True
            except Exception:
                return False
            return False
        if self._current_agent is None or self._panel_mode != DetailPanelMode.LLM_CALLS:
            return False
        llm_calls_scroll = self.query_one("#agent-llm-calls-scroll", VerticalScroll)
        return not llm_calls_scroll.has_class("hidden")

    @property
    def llm_calls_detail_level(self) -> ToolDetailLevel:
        """Current detail level for the LLM Calls panel."""
        llm_calls_panel = self._llm_calls_panel_or_none()
        return (
            ToolDetailLevel.COMPACT
            if llm_calls_panel is None
            else llm_calls_panel.detail_level
        )

    def expand_tools_detail(self) -> bool:
        """Expand the visible LLM Calls panel by one detail level."""
        llm_calls_panel = self._llm_calls_panel_or_none()
        return False if llm_calls_panel is None else llm_calls_panel.expand_detail()

    def collapse_tools_detail(self) -> bool:
        """Collapse the visible LLM Calls panel by one detail level."""
        llm_calls_panel = self._llm_calls_panel_or_none()
        return False if llm_calls_panel is None else llm_calls_panel.collapse_detail()

    def set_llm_calls_detail_level(self, level: ToolDetailLevel | int) -> bool:
        """Set the visible LLM Calls panel detail level."""
        llm_calls_panel = self._llm_calls_panel_or_none()
        return (
            False
            if llm_calls_panel is None
            else llm_calls_panel.set_detail_level(level)
        )

    def _llm_calls_panel_or_none(self) -> AgentLLMCallsPanel | None:
        if bool(getattr(self, "decks_enabled", False)):
            try:
                from .decks.model import DeckId as _DeckId

                focused = self.deck_area.focused_panel()  # type: ignore[attr-defined]
                if focused.deck is _DeckId.TOOLS:
                    return focused.tools_view
                for panel in self.deck_area.visible_panels():  # type: ignore[attr-defined]
                    if panel.deck is _DeckId.TOOLS:
                        return panel.tools_view
            except Exception:
                return None
            return None
        try:
            return self.query_one("#agent-llm-calls-panel", AgentLLMCallsPanel)
        except NoMatches:
            return None

    def is_info_mode(self) -> bool:
        """Check if the panel is in info-only mode.

        Returns:
            True if metadata is the effective visible detail panel.
        """
        return not self.is_file_visible() and not self.is_llm_calls_visible()

    def is_file_visible(self) -> bool:
        """Check if the file panel is currently visible.

        Returns:
            True if the file panel is visible, False otherwise.
        """
        if bool(getattr(self, "decks_enabled", False)):
            if self._current_agent is None:
                return False
            try:
                from .decks.model import DeckId as _DeckId

                for panel in self.deck_area.visible_panels():  # type: ignore[attr-defined]
                    if panel.deck is _DeckId.FILES and not panel._deck_is_empty(
                        _DeckId.FILES
                    ):
                        return True
            except Exception:
                return False
            return False
        if self._current_agent is None:
            return False
        file_scroll = self.query_one("#agent-file-scroll", VerticalScroll)
        return not file_scroll.has_class("hidden")

    def is_metadata_visible(self) -> bool:
        """Return whether either metadata scroll variant is visible."""
        if bool(getattr(self, "decks_enabled", False)):
            try:
                from .decks.model import DeckId as _DeckId

                return any(
                    panel.deck is _DeckId.MAIN
                    for panel in self.deck_area.visible_panels()  # type: ignore[attr-defined]
                )
            except Exception:
                return False
        prompt_scroll = self.query_one("#agent-prompt-scroll", VerticalScroll)
        search_scroll = self.query_one("#agent-search-scroll", VerticalScroll)
        return not (
            prompt_scroll.has_class("hidden") and search_scroll.has_class("hidden")
        )

    def effective_detail_scroll_id(self) -> str:
        """Return the scroll container that currently owns detail navigation."""
        if bool(getattr(self, "decks_enabled", False)):
            try:
                panel = self.deck_area.focused_panel()  # type: ignore[attr-defined]
                return f"#{panel.active_scroll().id}"
            except Exception:
                return "#agent-deck-area"
        if self.is_llm_calls_visible():
            return "#agent-llm-calls-scroll"
        if self.is_file_visible():
            return "#agent-file-scroll"
        search_scroll = self.query_one("#agent-search-scroll", VerticalScroll)
        if not search_scroll.has_class("hidden"):
            return "#agent-search-scroll"
        return "#agent-prompt-scroll"

    def get_editor_file_info(self) -> tuple[str | None, str | None, str]:
        """Get file path, content, and suffix for opening in an editor.

        Returns:
            (file_path, content, suffix) where:
            - file_path is set if a real file can be opened directly
            - content is set if a temp file should be created
            - suffix is the file extension for the temp file
        """
        if bool(getattr(self, "decks_enabled", False)):
            try:
                from .decks.model import DeckId as _DeckId

                panel = self.deck_area.focused_panel()  # type: ignore[attr-defined]
                if panel.deck is _DeckId.FILES:
                    view = panel.file_view
                    return (
                        view.get_current_file_path(),
                        view.get_current_content(),
                        ".diff",
                    )
                if panel.deck is _DeckId.TOOLS:
                    return (None, panel.tools_view.get_llm_calls_text(), ".md")
            except Exception:
                pass
            return (None, None, "")
        if self.is_file_visible():
            file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
            return (
                file_panel.get_current_file_path(),
                file_panel.get_current_content(),
                ".diff",
            )
        if self.is_llm_calls_visible():
            llm_calls_panel = self.query_one(
                "#agent-llm-calls-panel", AgentLLMCallsPanel
            )
            return (None, llm_calls_panel.get_llm_calls_text(), ".md")
        return (None, None, "")

    def get_current_image_path(self) -> str | None:
        """Return the currently visible image path, or None."""
        if bool(getattr(self, "decks_enabled", False)):
            try:
                from .decks.model import DeckId as _DeckId

                panel = self.deck_area.focused_panel()  # type: ignore[attr-defined]
                if panel.deck is not _DeckId.FILES:
                    return None
                return panel.file_view.get_current_image_path()
            except Exception:
                return None
        if not self.is_file_visible():
            return None
        file_panel = self.query_one("#agent-file-panel", AgentFilePanel)
        return file_panel.get_current_image_path()

    @property
    def attempt_view_mode(self) -> str:
        """Current mode for rendering the attempt history ("merged" or "current-only")."""
        return self._attempt_view_mode

    def toggle_attempt_view(self) -> bool:
        """Cycle between merged / current-only attempt view modes.

        Returns True if the view was re-rendered (an agent is selected).
        """
        self._attempt_view_mode = (
            "current-only" if self._attempt_view_mode == "merged" else "merged"
        )
        if self._current_agent is not None:
            self.update_display(
                self._current_agent, attempt_number=self._current_attempt_number
            )
            return True
        return False

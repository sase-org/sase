"""Empty/tribe states, file navigation, and visibility queries for AgentDetail."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..util.trace import tui_trace
from .file_panel._messages import LinkedDeltasRefreshed
from .llm_calls_panel import AgentLLMCallsPanel, ToolDetailLevel

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.agent_tribe_summary import (
        AgentTribeSummarySnapshot,
        TribePanelIdentity,
    )


class AgentDetailStateMixin:
    """Mixin for AgentDetail secondary states and visibility queries.

    Covers the empty and tribe-summary documents, file-panel navigation,
    LLM Calls detail levels, visibility predicates, editor export, and the
    attempt-history view mode. Deck panels own their rendering and
    availability state.
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

    @property
    def metadata_identity(self) -> object | None:
        raise NotImplementedError

    def _publish_metadata_identity_change(self, previous: object | None) -> None:
        raise NotImplementedError

    if TYPE_CHECKING:

        def _sync_header_visibility(self) -> None: ...

        def update_display(
            self,
            agent: Agent,
            stale_threshold_seconds: int = 10,
            attempt_number: int | None = None,
        ) -> None: ...

    def show_empty(self) -> None:
        """Show empty state for all panels."""
        previous_identity = self.metadata_identity
        self._deck_show_empty()  # type: ignore[attr-defined]
        self._publish_metadata_identity_change(previous_identity)
        self._sync_header_visibility()

    def show_tribe_summary(
        self,
        snapshot: AgentTribeSummarySnapshot,
        *,
        cheap: bool = False,
    ) -> None:
        """Show a tribe document on the regular fold-aware prompt surface."""
        previous_identity = self.metadata_identity
        self._deck_show_tribe_summary(snapshot, cheap=cheap)  # type: ignore[attr-defined]
        self._publish_metadata_identity_change(previous_identity)
        self._sync_header_visibility()

    def refresh_current_file(self, agent: Agent) -> None:
        """Force refresh the file for the given agent.

        Args:
            agent: The Agent to refresh file for.
        """
        with tui_trace("agent_detail.refresh_current_file"):
            try:
                from .decks.model import DeckId as _DeckId

                for panel in self.deck_area.panels_showing(_DeckId.FILES):  # type: ignore[attr-defined]
                    panel.file_view.refresh_file(agent)
            except Exception:
                pass

    def cycle_next_file(self) -> None:
        """Cycle to the next file in the file panel."""
        try:
            self.deck_area.focused_panel().file_view.next_file()  # type: ignore[attr-defined]
        except Exception:
            pass

    def cycle_prev_file(self) -> None:
        """Cycle to the previous file in the file panel."""
        try:
            self.deck_area.focused_panel().file_view.prev_file()  # type: ignore[attr-defined]
        except Exception:
            pass

    def on_linked_deltas_refreshed(self, message: LinkedDeltasRefreshed) -> None:
        """Refresh file-panel linked pages after the prompt worker updates cache."""
        if (
            self._current_agent is None
            or self._current_agent.identity != message.agent_identity
        ):
            return
        try:
            from .decks.model import DeckId as _DeckId

            for panel in self.deck_area.panels_showing(_DeckId.FILES):  # type: ignore[attr-defined]
                panel.file_view.reconcile_linked_pages(self._current_agent)
        except Exception:
            pass
        message.stop()

    def is_llm_calls_visible(self) -> bool:
        """Check if the LLM Calls panel is currently visible.

        Returns:
            True if the LLM Calls panel is visible, False otherwise.
        """
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
        try:
            focused_view = self.focused_tools_view()  # type: ignore[attr-defined]
            return focused_view
        except Exception:
            return None

    def is_file_visible(self) -> bool:
        """Check if the file panel is currently visible.

        Returns:
            True if the file panel is visible, False otherwise.
        """
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

    def is_metadata_visible(self) -> bool:
        """Return whether the Main deck is visible."""
        try:
            from .decks.model import DeckId as _DeckId

            return any(
                panel.deck is _DeckId.MAIN
                for panel in self.deck_area.visible_panels()  # type: ignore[attr-defined]
            )
        except Exception:
            return False

    def effective_detail_scroll_id(self) -> str:
        """Return the scroll container that currently owns detail navigation."""
        try:
            panel = self.deck_area.focused_panel()  # type: ignore[attr-defined]
            return f"#{panel.active_scroll().id}"
        except Exception:
            return "#agent-deck-area"

    def get_editor_file_info(self) -> tuple[str | None, str | None, str]:
        """Get file path, content, and suffix for opening in an editor.

        Returns:
            (file_path, content, suffix) where:
            - file_path is set if a real file can be opened directly
            - content is set if a temp file should be created
            - suffix is the file extension for the temp file
        """
        try:
            from rich.console import Group

            from .decks.model import DeckId as _DeckId
            from .renderable_text import renderable_to_text

            panel = self.deck_area.focused_panel()  # type: ignore[attr-defined]
            deck = self.focused_deck()  # type: ignore[attr-defined]
            if deck is _DeckId.MAIN or panel.deck is _DeckId.MAIN:
                card_id = panel.active_main_card()
                if card_id is not None:
                    card = panel._main_document.card(card_id)
                    if card is not None:
                        text = renderable_to_text(Group(*card.renderables))
                        return (None, text, ".md")
                return (None, None, "")
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

    def get_current_image_path(self) -> str | None:
        """Return the currently visible image path, or None."""
        try:
            view = self.focused_file_view()  # type: ignore[attr-defined]
            if view is None:
                return None
            return view.get_current_image_path()
        except Exception:
            return None

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

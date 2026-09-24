"""Agent detail widget for sase's TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from ._agent_detail_decks import AgentDetailDeckMixin
from ._agent_detail_display import AgentDetailDisplayMixin
from ._agent_detail_helpers import agent_prompt_panel_type
from ._agent_detail_jump import AgentDetailJumpMixin
from ._agent_detail_panels import (
    AgentDetailPanelMixin,
    DetailLayoutMode,
    DetailPanelMode,
)
from ._agent_detail_state import AgentDetailStateMixin
from .file_panel import AgentFilePanel
from .llm_calls_panel import AgentLLMCallsPanel

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.agent_tribe_summary import TribePanelIdentity


class AgentMetadataIdentityChanged(Message):
    """The document represented by the metadata panel changed identity."""

    def __init__(self, identity: object | None) -> None:
        super().__init__()
        self.identity = identity


class AgentDetail(
    AgentDetailDeckMixin,
    AgentDetailDisplayMixin,
    AgentDetailStateMixin,
    AgentDetailPanelMixin,
    AgentDetailJumpMixin,
    Static,
):
    """Combined widget with prompt and file panels."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the agent detail view."""
        super().__init__(**kwargs)
        self._detail_layout_mode: DetailLayoutMode = DetailLayoutMode.METADATA_ONLY
        self._panel_mode: DetailPanelMode = DetailPanelMode.AUTO
        self._current_agent: Agent | None = None
        self._current_tribe_identity: TribePanelIdentity | None = None
        self._has_file_content: bool = False
        self._has_llm_calls_content: bool = False
        self._file_count: int = 0
        self._file_index: int = 0
        self._file_visible_lines: int = 0
        self._file_total_lines: int = 0
        self._file_content_capped: bool = False
        self._attempt_view_mode: str = "merged"
        self._current_attempt_number: int | None = None
        # Two-phase update guard. ``update_display_immediate`` and
        # ``update_display`` both bump this counter; debounced workers
        # capture the value at start and discard their result if the
        # generation has advanced before they complete.
        self._agent_detail_generation: int = 0
        self._decks_enabled = False
        from .decks.main_document import EMPTY_MAIN_DOCUMENT

        self._main_deck_document = EMPTY_MAIN_DOCUMENT

    def compose(self) -> ComposeResult:
        """Compose the two-panel layout (prompt and file)."""
        from .agent_header_panel import AgentHeaderPanel
        from .agent_jump_panel import AgentJumpPanel
        from .decks.area import DeckArea

        AgentPromptPanel = agent_prompt_panel_type()
        try:
            from .decks.flag import agent_decks_enabled

            decks_enabled = bool(agent_decks_enabled())
        except Exception:
            decks_enabled = False
        self._decks_enabled = decks_enabled
        with Vertical(id="agent-detail-layout"):
            yield AgentHeaderPanel(id="agent-header-panel", classes="hidden")
            if decks_enabled:
                with Vertical(id="agent-deck-source-host"):
                    with VerticalScroll(id="agent-prompt-scroll"):
                        yield AgentPromptPanel(
                            id="agent-prompt-panel", classes="-deck-source"
                        )
                    with VerticalScroll(id="agent-search-scroll", classes="hidden"):
                        yield Static(id="agent-search-panel")
                    yield Static(id="agent-search-command", classes="hidden")
                yield DeckArea(id="agent-deck-area", classes="-single")
                yield AgentJumpPanel(id="agent-jump-panel", classes="hidden")
                return
            with VerticalScroll(id="agent-prompt-scroll", classes="expanded"):
                yield AgentPromptPanel(id="agent-prompt-panel")
            with VerticalScroll(id="agent-search-scroll", classes="hidden"):
                yield Static(id="agent-search-panel")
            yield Static(id="agent-search-command", classes="hidden")
            with VerticalScroll(id="agent-file-scroll", classes="hidden"):
                yield AgentFilePanel(id="agent-file-panel")
            with VerticalScroll(id="agent-llm-calls-scroll", classes="hidden"):
                yield AgentLLMCallsPanel(id="agent-llm-calls-panel")
            yield AgentJumpPanel(id="agent-jump-panel", classes="hidden")

    @property
    def metadata_identity(self) -> object | None:
        """Return a stable identity for the document in the metadata panel."""
        tribe_identity = getattr(self, "_current_tribe_identity", None)
        if tribe_identity is not None:
            return ("tribe", tribe_identity)
        current_agent = getattr(self, "_current_agent", None)
        if current_agent is not None:
            return (
                "agent",
                current_agent.identity,
                getattr(self, "_current_attempt_number", None),
            )
        return None

    def on_mount(self) -> None:
        """Attach the prompt panel's sinks to the header and jump panels."""
        try:
            prompt_panel = self.query_one(
                "#agent-prompt-panel", agent_prompt_panel_type()
            )
        except Exception:
            return
        try:
            prompt_panel.attach_identity_header_sink(self._on_identity_header)
        except Exception:
            pass
        if self.decks_enabled:
            try:
                prompt_panel.attach_main_document_sink(self._on_main_document)
            except Exception:
                pass
        self._sync_header_visibility()
        self._attach_jump_panel_sink()

    def _header_panel_or_none(self) -> Any | None:
        """Return the header panel when mounted, else None."""
        try:
            from .agent_header_panel import AgentHeaderPanel

            return self.query_one("#agent-header-panel", AgentHeaderPanel)
        except Exception:
            return None

    def _on_identity_header(self, header: Any | None) -> None:
        """Show the published identity, then sync header visibility."""
        panel = self._header_panel_or_none()
        if panel is None:
            return
        try:
            panel.show_identity(header)
        except Exception:
            pass
        self._sync_header_visibility()

    def _sync_header_visibility(self) -> None:
        """Hide the header unless the current document published an identity."""
        panel = self._header_panel_or_none()
        if panel is None:
            return
        try:
            visible = bool(panel.has_identity)
        except Exception:
            visible = False
        try:
            if visible:
                panel.remove_class("hidden")
            else:
                panel.add_class("hidden")
        except Exception:
            pass

    def header_toggle_available(self) -> bool:
        """Return whether the header panel can be toggled."""
        panel = self._header_panel_or_none()
        if panel is None:
            return False
        try:
            return bool(panel.has_identity) and not panel.has_class("hidden")
        except Exception:
            return False

    def toggle_header_expanded(self) -> bool:
        """Flip the header panel state and keep a bottom pin in place."""
        panel = self._header_panel_or_none()
        if panel is None:
            return False
        try:
            expanded = bool(panel.toggle_expanded())
        except Exception:
            return False
        try:
            if self.decks_enabled:
                area = self.deck_area
                for deck_panel in area.visible_panels():
                    try:
                        main_view = deck_panel.main_view
                    except Exception:
                        continue
                    if bool(getattr(main_view, "is_pinned_to_bottom", False)):
                        reschedule = getattr(
                            main_view, "_schedule_bottom_pin_reapply", None
                        )
                        if callable(reschedule):
                            reschedule()
                return expanded
            prompt_panel = self.query_one(
                "#agent-prompt-panel", agent_prompt_panel_type()
            )
            if bool(getattr(prompt_panel, "is_pinned_to_bottom", False)):
                reschedule = getattr(prompt_panel, "_schedule_bottom_pin_reapply", None)
                if callable(reschedule):
                    reschedule()
        except Exception:
            pass
        return expanded

    def on_agent_metadata_identity_changed(
        self, message: AgentMetadataIdentityChanged
    ) -> None:
        """Reset panel scrolls when the metadata document identity changes."""
        panel = self._header_panel_or_none()
        if panel is not None:
            try:
                panel.scroll_to(y=0, animate=False)
            except Exception:
                pass
        self._reset_jump_panel_scroll()

    def _active_metadata_scroll(self) -> VerticalScroll:
        """Return the search overlay or the native prompt scroll."""
        search_scroll = self.query_one("#agent-search-scroll", VerticalScroll)
        if not search_scroll.has_class("hidden"):
            return search_scroll
        return self.query_one("#agent-prompt-scroll", VerticalScroll)

    def _publish_metadata_identity_change(self, previous: object | None) -> None:
        current = self.metadata_identity
        if current != previous:
            panel = self._header_panel_or_none()
            if panel is not None:
                try:
                    panel.scroll_to(y=0, animate=False)
                except Exception:
                    pass
            self._reset_jump_panel_scroll()
            self.post_message(AgentMetadataIdentityChanged(current))

    def toggle_layout(self) -> None:
        """Cycle to the next saved detail layout."""
        super().toggle_layout()

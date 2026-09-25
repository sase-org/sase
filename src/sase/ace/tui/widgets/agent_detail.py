"""Agent detail widget for sase's TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from ._agent_detail_deck_layout import AgentDetailDeckLayoutMixin
from ._agent_detail_deck_targets import AgentDetailDeckTargetsMixin
from ._agent_detail_decks import AgentDetailDeckMixin
from ._agent_detail_display import AgentDetailDisplayMixin
from ._agent_detail_helpers import agent_prompt_panel_type
from ._agent_detail_jump import AgentDetailJumpMixin
from ._agent_detail_state import AgentDetailStateMixin

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.agent_tribe_summary import TribePanelIdentity


class AgentMetadataIdentityChanged(Message):
    """The document represented by the metadata panel changed identity."""

    def __init__(self, identity: object | None) -> None:
        super().__init__()
        self.identity = identity


class AgentDetail(
    AgentDetailDeckLayoutMixin,
    AgentDetailDeckTargetsMixin,
    AgentDetailDeckMixin,
    AgentDetailDisplayMixin,
    AgentDetailStateMixin,
    AgentDetailJumpMixin,
    Static,
):
    """Combined widget with prompt and file panels."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the agent detail view."""
        super().__init__(**kwargs)
        self._current_agent: Agent | None = None
        self._current_tribe_identity: TribePanelIdentity | None = None
        self._attempt_view_mode: str = "merged"
        self._current_attempt_number: int | None = None
        # Two-phase update guard. ``update_display_immediate`` and
        # ``update_display`` both bump this counter; debounced workers
        # capture the value at start and discard their result if the
        # generation has advanced before they complete.
        self._agent_detail_generation: int = 0
        from .decks.main_document import EMPTY_MAIN_DOCUMENT

        self._main_deck_document = EMPTY_MAIN_DOCUMENT

    def compose(self) -> ComposeResult:
        """Compose the deck layout."""
        from .agent_header_panel import AgentHeaderPanel
        from .agent_jump_panel import AgentJumpPanel
        from .decks.area import DeckArea

        AgentPromptPanel = agent_prompt_panel_type()
        with Vertical(id="agent-detail-layout"):
            yield AgentHeaderPanel(id="agent-header-panel", classes="hidden")
            with Vertical(id="agent-deck-main-source"):
                yield AgentPromptPanel(id="agent-prompt-panel", classes="-deck-source")
            yield DeckArea(id="agent-deck-area", classes="-single")
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
            prompt_panel.attach_identity_header_sink(
                self._on_identity_header, detach_xprompt=True
            )
        except Exception:
            pass
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
            before = int(panel.rendered_row_count)
        except Exception:
            before = -1
        try:
            panel.show_identity(header)
        except Exception:
            pass
        try:
            if int(panel.rendered_row_count) != before:
                self.reapply_main_view_pins()  # type: ignore[attr-defined]
        except Exception:
            pass
        self._sync_header_visibility()

    def on_resize(self, event: Any = None) -> None:
        """Refit the header preview when the detail column height changes."""
        panel = self._header_panel_or_none()
        if panel is None:
            return
        rows: int | None = None
        try:
            if event is not None:
                rows = int(event.size.height)
        except Exception:
            rows = None
        if rows is None or rows <= 0:
            try:
                rows = int(self.size.height or 0)
            except Exception:
                rows = None
        if rows is None or rows <= 0:
            return
        try:
            before = int(panel.rendered_row_count)
        except Exception:
            before = -1
        try:
            panel.set_column_rows(rows)
        except Exception:
            return
        try:
            if int(panel.rendered_row_count) != before:
                self.reapply_main_view_pins()  # type: ignore[attr-defined]
        except Exception:
            pass

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
            self.reapply_main_view_pins()  # type: ignore[attr-defined]
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

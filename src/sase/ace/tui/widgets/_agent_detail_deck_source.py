"""Main-document sink and source wiring for AgentDetail deck mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .decks.main_document import MainDeckDocument, build_main_deck_document
from .decks.model import DeckId

if TYPE_CHECKING:
    from ..models.agent import Agent


class AgentDetailDeckSourceMixin:
    """Mixin providing the deck Main sink, source panel, and accessors."""

    _main_deck_document: MainDeckDocument
    _attempt_view_mode: str
    _agent_detail_generation: int

    @property
    def deck_area(self) -> Any:
        """Return the mounted DeckArea."""
        from .decks.area import DeckArea

        return self.query_one("#agent-deck-area", DeckArea)  # type: ignore[attr-defined]

    def _deck_source_panel(self) -> Any:
        from ._agent_detail_helpers import agent_prompt_panel_type

        return self.query_one("#agent-prompt-panel", agent_prompt_panel_type())  # type: ignore[attr-defined]

    def _on_main_document(
        self, content: object, partial: bool, digest: str | None
    ) -> None:
        """Sink Main documents from the hidden prompt source."""
        try:
            subject = self.metadata_identity  # type: ignore[attr-defined]
        except Exception:
            subject = None
        document = build_main_deck_document(
            content, subject=subject, partial=partial, digest=digest
        )
        self._main_deck_document = document
        try:
            area = self.deck_area
        except Exception:
            return
        try:
            panels = area.panels_showing(DeckId.MAIN)
        except Exception:
            panels = ()
        for panel in panels:
            try:
                index = panel.panel_index
                preferred = area.state.panels[index].preferred_card_for(DeckId.MAIN)
            except Exception:
                preferred = None
            try:
                panel.show_main_document(document, preferred_card=preferred)
            except Exception:
                pass
            try:
                panel.refresh_chrome()
            except Exception:
                pass

    def _update_main_source(self, agent: Agent, attempt_number: int | None) -> None:
        from ._agent_detail_helpers import agent_prompt_panel_type

        prompt_panel = self._deck_source_panel()
        prompt_panel.attempt_view_mode = self._attempt_view_mode
        prompt_panel.attempt_pinned_number = attempt_number
        generation = self._agent_detail_generation
        set_render_context = getattr(
            prompt_panel, "set_agent_detail_render_context", None
        )
        if callable(set_render_context):
            set_render_context(
                generation=generation,
                attempt_view_mode=self._attempt_view_mode,
                attempt_pinned_number=attempt_number,
                is_current=self._is_agent_detail_render_current,  # type: ignore[attr-defined]
            )
        should_async = self._should_render_workflow_detail_async(agent, attempt_number)  # type: ignore[attr-defined]
        _PromptPanel = agent_prompt_panel_type()
        _ = _PromptPanel
        if should_async:
            prompt_panel.start_workflow_detail_render(
                agent,
                generation=generation,
                attempt_view_mode=self._attempt_view_mode,
                attempt_pinned_number=attempt_number,
                is_current=self._is_agent_detail_render_current,  # type: ignore[attr-defined]
            )
        else:
            prompt_panel.update_display(agent)


__all__ = ["AgentDetailDeckSourceMixin"]

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
        self._deliver_main_document(document)

    def _deliver_main_document(
        self, document: MainDeckDocument, *, show_panels: bool = True
    ) -> None:
        """Store DOCUMENT and re-sync availability when its cards changed.

        With ``show_panels`` (the async sink path) the document is also
        pushed to the visible Main panels. The sync re-sync path passes
        ``show_panels=False``: the display path's own view refresh paints
        the just-rendered content immediately afterwards with its scroll
        and pin state intact, while storing here keeps the subtitle
        counts in sync.
        """
        try:
            prev_card_ids = tuple(self._main_deck_document.card_ids)
        except Exception:
            prev_card_ids = ()
        self._main_deck_document = document
        if show_panels:
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
        try:
            cards_changed = tuple(document.card_ids) != prev_card_ids
        except Exception:
            cards_changed = True
        if cards_changed and not self._sync_main_display_active():
            # Keep the deck subtitle counts in sync with documents that
            # arrive after the display path ran (async worker and
            # enrichment deliveries): without this the subtitle can stick
            # at ``main 0`` while the Context card is already painted
            # (sase-1a3): a capture race, not a data race. Deliveries made
            # while the sync display runs are skipped here on purpose: the
            # display path's own trailing availability refresh already
            # covers them, and an extra mid-display refresh perturbs
            # settling chrome (sase-1kl.2).
            try:
                self._deck_refresh_availability()  # type: ignore[attr-defined]
            except Exception:
                pass

    def _sync_main_display_active(self) -> bool:
        """Return whether a sync main-source display is running.

        Used as a reentrancy counter so sink deliveries made while the
        sync display path runs skip their eager availability refresh:
        the display path's own trailing refresh covers them.
        """
        try:
            return int(getattr(self, "_sync_main_display_depth", 0) or 0) > 0
        except Exception:
            return False

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
        try:
            self._sync_main_display_depth = (  # type: ignore[attr-defined]
                int(getattr(self, "_sync_main_display_depth", 0) or 0) + 1
            )
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
                self._resync_main_sink_after_sync_display(agent, prompt_panel)
        finally:
            try:
                self._sync_main_display_depth = (  # type: ignore[attr-defined]
                    int(getattr(self, "_sync_main_display_depth", 0) or 0) - 1
                )
            except Exception:
                pass

    def _resync_main_sink_after_sync_display(
        self, agent: Agent, prompt_panel: Any
    ) -> None:
        """Re-push the Main sink when the sync render was deduped away.

        The prompt panel skips its Main sink when the freshly rendered
        content is digest-identical to what it already shows, which is
        the common case when two agents share the same placeholder
        (for example ``No prompt file found``). The deck source, however,
        was just reset for the new agent, so without a sink delivery the
        Main document — and the ``main N`` subtitle refreshed from it —
        sticks at empty until an enrichment worker happens to re-render
        with different content. That wait is unbounded under load and is
        the ``main 0``/``main 1`` capture flip behind sase-1a3. Store the
        panel's just-rendered content when the stored document does not
        belong to the current subject; a fresh delivery for the same
        subject is already in place, so this is a no-op in steady state.
        The document is stored without pushing it to the panels: the
        display path's own view refresh paints it immediately afterwards
        with scroll and pin state intact.
        """
        del agent
        try:
            if getattr(self, "_current_tribe_identity", None) is not None:
                return
            if getattr(self, "_current_agent", None) is None:
                return
            subject = self.metadata_identity  # type: ignore[attr-defined]
        except Exception:
            return
        if subject is None:
            return
        try:
            current_subject = getattr(self._main_deck_document, "subject", None)
        except Exception:
            return
        try:
            same_subject = current_subject == subject
        except Exception:
            same_subject = False
        if same_subject:
            return
        try:
            content = getattr(prompt_panel, "_last_prompt_panel_content", None)
            digest = getattr(prompt_panel, "_last_prompt_panel_digest", None)
            partial = bool(getattr(prompt_panel, "_main_document_partial", False))
        except Exception:
            return
        if content is None:
            return
        try:
            document = build_main_deck_document(
                content, subject=subject, partial=partial, digest=digest
            )
        except Exception:
            return
        try:
            self._deliver_main_document(document, show_panels=False)
        except Exception:
            pass


__all__ = ["AgentDetailDeckSourceMixin"]

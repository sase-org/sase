"""Deck-mode compose and delegation for AgentDetail."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .decks.availability import (
    DeckAvailability,
    probe_files_deck,
    probe_tools_deck,
)
from .decks.main_document import (
    EMPTY_MAIN_DOCUMENT,
    MainDeckDocument,
    build_main_deck_document,
)
from .decks.model import DeckId

if TYPE_CHECKING:
    from ..models.agent import Agent


class AgentDetailDeckMixin:
    """Mixin providing deck-mode Main sink, refresh and accessors."""

    _decks_enabled: bool = False
    _main_deck_document: MainDeckDocument = EMPTY_MAIN_DOCUMENT
    _current_agent: Any | None
    _current_tribe_identity: Any | None
    _current_attempt_number: int | None
    _attempt_view_mode: str
    _agent_detail_generation: int

    @property
    def decks_enabled(self) -> bool:
        """Whether this detail view composes deck panels."""
        return bool(getattr(self, "_decks_enabled", False))

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
                preferred = area.state.panels[index].preferred_card
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

    def _deck_refresh_views(
        self, agent: Agent, stale_threshold_seconds: int, attempt_number: int | None
    ) -> None:
        from ..llm_calls import supports_slow_tool_sources
        from ._agent_detail_files import load_deck_file_view

        try:
            area = self.deck_area
            panels = area.visible_panels()
        except Exception:
            return
        seen: set[DeckId] = set()
        for panel in panels:
            if panel.deck is DeckId.FILES:
                if DeckId.FILES in seen:
                    try:
                        loader = getattr(self, "_load_files_panel_from_cache", None)
                        if callable(loader):
                            loader(panel, agent)
                    except Exception:
                        pass
                    continue
                seen.add(DeckId.FILES)
                try:
                    loaded = load_deck_file_view(
                        panel.file_view,
                        agent,
                        attempt_number=attempt_number,
                        stale_threshold_seconds=stale_threshold_seconds,
                    )
                    if not loaded:
                        panel.set_availability(
                            {
                                **panel._availability,
                                DeckId.FILES: DeckAvailability(False, 0),
                            }
                        )
                except Exception:
                    pass
            elif panel.deck is DeckId.TOOLS:
                if DeckId.TOOLS in seen:
                    try:
                        loader = getattr(self, "_load_tools_panel_from_cache", None)
                        if callable(loader):
                            loader(panel, agent)
                    except Exception:
                        pass
                    continue
                seen.add(DeckId.TOOLS)
                try:
                    if (
                        attempt_number is None
                        and not agent.is_clan_container
                        and not agent.is_proc_shell
                        and supports_slow_tool_sources(agent)
                    ):
                        panel.tools_view.update_display(agent)
                    else:
                        panel.tools_view.show_empty()
                        panel.set_availability(
                            {
                                **panel._availability,
                                DeckId.TOOLS: DeckAvailability(False, 0),
                            }
                        )
                except Exception:
                    pass
        # Main is handled by the sink.

    def _deck_refresh_availability(self) -> None:
        agent = self._current_agent
        attempt_number = self._current_attempt_number
        try:
            area = self.deck_area
            panels = area.visible_panels()
        except Exception:
            return
        for panel in panels:
            if agent is None:
                availability = {
                    DeckId.MAIN: DeckAvailability(
                        bool(self._main_deck_document.cards),
                        len(self._main_deck_document.cards),
                    ),
                    DeckId.FILES: DeckAvailability(False, 0),
                    DeckId.TOOLS: DeckAvailability(False, 0),
                }
            else:
                availability = {
                    DeckId.MAIN: DeckAvailability(
                        bool(self._main_deck_document.cards),
                        len(self._main_deck_document.cards),
                    ),
                    DeckId.FILES: probe_files_deck(
                        agent, attempt_number=attempt_number
                    ),
                    DeckId.TOOLS: probe_tools_deck(
                        agent, attempt_number=attempt_number
                    ),
                }
            # Panel message handlers override per-deck observed truth.
            try:
                observed_files = panel._availability.get(DeckId.FILES)
                observed_tools = panel._availability.get(DeckId.TOOLS)
                if panel.deck is DeckId.FILES and observed_files is not None:
                    if observed_files.has_content is not None:
                        availability[DeckId.FILES] = observed_files
                if panel.deck is DeckId.TOOLS and observed_tools is not None:
                    if observed_tools.has_content is not None:
                        availability[DeckId.TOOLS] = observed_tools
            except Exception:
                pass
            try:
                panel.set_availability(dict(availability))
            except Exception:
                pass

    def _deck_update_display_impl(
        self, agent: Agent, stale_threshold_seconds: int, attempt_number: int | None
    ) -> None:
        prev_agent = self._current_agent
        self._current_agent = agent
        self._current_attempt_number = attempt_number
        if prev_agent is not None and prev_agent.identity != agent.identity:
            self._main_deck_document = EMPTY_MAIN_DOCUMENT
        self._update_main_source(agent, attempt_number)
        self._deck_refresh_views(agent, stale_threshold_seconds, attempt_number)
        self._deck_refresh_availability()

    def _deck_show_empty(self) -> None:
        from ._agent_detail_helpers import agent_prompt_panel_type  # noqa: F401

        self._agent_detail_generation += 1
        self._current_agent = None
        self._current_tribe_identity = None
        self._current_attempt_number = None
        try:
            source = self._deck_source_panel()
            source.show_empty()
        except Exception:
            pass
        # The sink produces an empty document because the subject is None.
        try:
            area = self.deck_area
            for panel in area.visible_panels():
                try:
                    panel.file_view.show_empty()
                except Exception:
                    pass
                try:
                    panel.tools_view.show_empty()
                except Exception:
                    pass
                try:
                    panel.set_availability(
                        {
                            DeckId.MAIN: DeckAvailability(False, 0),
                            DeckId.FILES: DeckAvailability(False, 0),
                            DeckId.TOOLS: DeckAvailability(False, 0),
                        }
                    )
                except Exception:
                    pass
                try:
                    panel.refresh_chrome()
                except Exception:
                    pass
        except Exception:
            pass

    def _deck_show_tribe_summary(self, snapshot: Any, *, cheap: bool = False) -> None:
        self._agent_detail_generation += 1
        self._current_agent = None
        self._current_tribe_identity = snapshot.container_identity
        self._current_attempt_number = None
        try:
            source = self._deck_source_panel()
            source.update_tribe_display(snapshot, cheap=cheap)
        except Exception:
            pass
        try:
            area = self.deck_area
            for panel in area.visible_panels():
                try:
                    panel.file_view.show_empty()
                except Exception:
                    pass
                try:
                    panel.tools_view.show_empty()
                except Exception:
                    pass
                try:
                    panel.set_availability(
                        {
                            DeckId.MAIN: DeckAvailability(
                                bool(self._main_deck_document.cards),
                                len(self._main_deck_document.cards),
                            ),
                            DeckId.FILES: DeckAvailability(False, 0),
                            DeckId.TOOLS: DeckAvailability(False, 0),
                        }
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def show_deck(self, panel_index: int, deck: DeckId) -> None:
        """Show ``deck`` on ``panel_index`` and load it for the current subject."""
        area = self.deck_area
        try:
            siblings = [
                p
                for p in area.visible_panels()
                if p.deck is deck and p.panel_index != panel_index
            ]
        except Exception:
            siblings = []
        is_duplicate = bool(siblings)
        area.set_panel_deck(panel_index, deck)
        panel = area.panel(panel_index)
        agent = self._current_agent
        attempt_number = self._current_attempt_number
        if agent is None:
            try:
                panel.refresh_chrome()
            except Exception:
                pass
            return
        if deck is DeckId.MAIN:
            try:
                preferred = area.state.panels[panel_index].preferred_card
            except Exception:
                preferred = None
            try:
                panel.show_main_document(
                    self._main_deck_document, preferred_card=preferred
                )
            except Exception:
                pass
        elif deck is DeckId.FILES:
            if is_duplicate:
                try:
                    loader = getattr(self, "_load_files_panel_from_cache", None)
                    if callable(loader) and loader(panel, agent):
                        self._deck_refresh_availability()
                        try:
                            panel.refresh_chrome()
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
            from ._agent_detail_files import load_deck_file_view

            try:
                load_deck_file_view(
                    panel.file_view,
                    agent,
                    attempt_number=attempt_number,
                    stale_threshold_seconds=10,
                )
            except Exception:
                pass
        else:
            if is_duplicate:
                try:
                    loader = getattr(self, "_load_tools_panel_from_cache", None)
                    if callable(loader) and loader(panel, agent):
                        self._deck_refresh_availability()
                        try:
                            panel.refresh_chrome()
                        except Exception:
                            pass
                        return
                except Exception:
                    pass
            from ..llm_calls import supports_slow_tool_sources

            try:
                if (
                    attempt_number is None
                    and not agent.is_clan_container
                    and not agent.is_proc_shell
                    and supports_slow_tool_sources(agent)
                ):
                    panel.tools_view.update_display(agent)
                else:
                    panel.tools_view.show_empty()
            except Exception:
                pass
        self._deck_refresh_availability()
        try:
            panel.refresh_chrome()
        except Exception:
            pass

    def set_deck_preferred_card(self, panel_index: int, card_id: str | None) -> None:
        """Delegate preferred-card updates to the deck area."""
        try:
            self.deck_area.set_preferred_card(panel_index, card_id)
        except Exception:
            pass

    def cycle_focused_deck_card(self, direction: int) -> str | None:
        """Cycle cards in the focused panel; Main choices stick."""
        try:
            area = self.deck_area
            panel = area.focused_panel()
        except Exception:
            return None
        try:
            shown = panel.cycle_card(direction)
        except Exception:
            return None
        if shown is not None:
            try:
                index = panel.panel_index
            except Exception:
                return shown
            self.set_deck_preferred_card(index, shown)
        return shown

    def cycle_focused_deck(self, direction: int) -> None:
        """Cycle the focused panel to the next/previous deck (wraps)."""
        from .decks.model import cycle_deck_id

        try:
            area = self.deck_area
            panel = area.focused_panel()
            index = panel.panel_index
        except Exception:
            return
        try:
            self.show_deck(index, cycle_deck_id(panel.deck, direction))
        except Exception:
            pass

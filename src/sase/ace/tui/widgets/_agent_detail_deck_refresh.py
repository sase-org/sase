"""Deck refresh, availability, and empty/tribe states for AgentDetail."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .decks.availability import (
    DeckAvailability,
    probe_files_deck,
    probe_final_deck,
    probe_tools_deck,
)
from .decks.main_document import EMPTY_MAIN_DOCUMENT, MainDeckDocument
from .decks.model import DeckId

if TYPE_CHECKING:
    from ..models.agent import Agent

log = logging.getLogger(__name__)


class AgentDetailDeckRefreshMixin:
    """Mixin refreshing deck views, availability, and empty/tribe states."""

    _main_deck_document: MainDeckDocument
    _current_agent: Any | None
    _current_tribe_identity: Any | None
    _current_attempt_number: int | None
    _agent_detail_generation: int

    def _deck_refresh_views(
        self, agent: Agent, stale_threshold_seconds: int, attempt_number: int | None
    ) -> None:
        from ._agent_detail_files import load_deck_file_view

        try:
            area = self.deck_area  # type: ignore[attr-defined]
            panels = area.visible_panels()
        except Exception:
            return
        seen: set[DeckId] = set()
        for panel in panels:
            if panel.deck is DeckId.MAIN:
                # Main is handled by the sink.
                continue
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
                    self._refresh_tools_panel(panel, agent, attempt_number)
                except Exception:
                    pass
            elif panel.deck is DeckId.FINAL:
                # Every FINAL panel paints its own view; the shared
                # stat-signature cache makes duplicates instant.
                try:
                    preferred = self._final_preferred_card(panel)
                except Exception:
                    preferred = None
                try:
                    panel.final_view.update_display(
                        agent,
                        attempt_number=attempt_number,
                        generation=self._agent_detail_generation,
                        preferred_card=preferred,
                    )
                except Exception:
                    pass
            else:
                log.warning(
                    "Unknown deck %r in _deck_refresh_views; skipping refresh",
                    panel.deck,
                )
                continue

    def _final_preferred_card(self, panel: Any) -> str | None:
        """Return the panel's sticky FINAL card from area state, if any."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            index = panel.panel_index
            return area.state.panels[index].preferred_card_for(DeckId.FINAL)
        except Exception:
            return None

    def _tools_preferred_card(self, panel: Any) -> str | None:
        """Return the panel's sticky Tools card from area state, if any."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            index = panel.panel_index
            return area.state.panels[index].preferred_card_for(DeckId.TOOLS)
        except Exception:
            return None

    def _refresh_tools_panel(
        self, panel: Any, agent: Agent, attempt_number: int | None
    ) -> None:
        """Refresh both Tools card hosts for ``agent``.

        The LLM Calls host keeps today's eligibility. The ``⚒ Runs``
        host additionally opens for monitor turns and named procs that
        own runs.
        """
        from ..llm_calls import supports_slow_tool_sources

        if (
            attempt_number is None
            and not agent.is_clan_container
            and not agent.is_named_proc
            and supports_slow_tool_sources(agent)
        ):
            try:
                panel.tools_view.update_display(agent)
            except Exception:
                pass
        else:
            try:
                panel.tools_view.show_empty()
            except Exception:
                pass
        try:
            preferred = self._tools_preferred_card(panel)
        except Exception:
            preferred = None
        if attempt_number is None and not agent.is_clan_container:
            try:
                panel.tool_runs_view.update_display(
                    agent,
                    attempt_number=attempt_number,
                    generation=self._agent_detail_generation,
                    preferred_card=preferred,
                )
            except Exception:
                pass
        else:
            try:
                panel.tool_runs_view.show_empty()
            except Exception:
                pass
        try:
            if preferred == "llm-calls":
                panel._store_document_active(DeckId.TOOLS, "llm-calls")
            else:
                panel._store_document_active(DeckId.TOOLS, None)
        except Exception:
            pass
        try:
            panel._sync_tools_hosts()
        except Exception:
            pass

    def _deck_refresh_availability(self) -> None:
        agent = self._current_agent
        attempt_number = self._current_attempt_number
        try:
            area = self.deck_area  # type: ignore[attr-defined]
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
                    DeckId.FINAL: DeckAvailability(False, 0),
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
                    DeckId.FINAL: probe_final_deck(
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
        self._update_main_source(agent, attempt_number)  # type: ignore[attr-defined]
        self._deck_refresh_views(agent, stale_threshold_seconds, attempt_number)
        self._deck_refresh_availability()

    def _deck_show_empty(self) -> None:
        from ._agent_detail_helpers import agent_prompt_panel_type  # noqa: F401

        self._agent_detail_generation += 1
        self._current_agent = None
        self._current_tribe_identity = None
        self._current_attempt_number = None
        try:
            source = self._deck_source_panel()  # type: ignore[attr-defined]
            source.show_empty()
        except Exception:
            pass
        # The sink produces an empty document because the subject is None.
        try:
            area = self.deck_area  # type: ignore[attr-defined]
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
                    panel.tool_runs_view.show_empty()
                except Exception:
                    pass
                try:
                    panel.final_view.show_empty()
                except Exception:
                    pass
                try:
                    panel.set_availability(
                        {
                            DeckId.MAIN: DeckAvailability(False, 0),
                            DeckId.FILES: DeckAvailability(False, 0),
                            DeckId.TOOLS: DeckAvailability(False, 0),
                            DeckId.FINAL: DeckAvailability(False, 0),
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
            source = self._deck_source_panel()  # type: ignore[attr-defined]
            source.update_tribe_display(snapshot, cheap=cheap)
        except Exception:
            pass
        try:
            area = self.deck_area  # type: ignore[attr-defined]
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
                    panel.tool_runs_view.show_empty()
                except Exception:
                    pass
                try:
                    panel.final_view.show_empty()
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
                            DeckId.FINAL: DeckAvailability(False, 0),
                        }
                    )
                except Exception:
                    pass
        except Exception:
            pass


__all__ = ["AgentDetailDeckRefreshMixin"]

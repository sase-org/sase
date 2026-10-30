"""Deck refresh, availability, and empty/tribe states for AgentDetail."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .decks.availability import (
    DeckAvailability,
    probe_files_deck,
    probe_final_deck,
    probe_record_deck,
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
    _current_record_subject: Any | None
    _current_tribe_identity: Any | None
    _tribe_document_complete: bool
    _current_attempt_number: int | None
    _agent_detail_generation: int

    def _record_display_kwargs(self, agent: Agent) -> dict[str, Any]:
        """Capture pump-safe Archive and live relation inputs for RECORD."""
        kwargs: dict[str, Any] = {
            "archive_light_row": None,
            "bundle_path": None,
            "related_live_names": (),
        }
        try:
            archive_read_only = bool(getattr(agent, "_archive_read_only", False))
        except Exception:
            archive_read_only = False
        if archive_read_only:
            try:
                from ..actions.agents._archive_view_selection import (
                    archive_read_only_context,
                )

                try:
                    app = getattr(self, "app", None)  # type: ignore[attr-defined]
                except Exception:
                    app = None
                for owner in (app, self):
                    if owner is None:
                        continue
                    context = archive_read_only_context(owner)
                    if context is not None:
                        kwargs["archive_light_row"] = getattr(
                            context, "light_row", None
                        )
                        break
            except Exception:
                pass
            for attr in ("bundle_path", "_dismissed_bundle_path"):
                try:
                    candidate = getattr(agent, attr, None)
                except Exception:
                    candidate = None
                if candidate:
                    kwargs["bundle_path"] = str(candidate)
                    break

        suffixes: list[str] = []
        for attr in (
            "parent_timestamp",
            "retry_of_timestamp",
            "retried_as_timestamp",
        ):
            try:
                value = getattr(agent, attr, None)
                if value:
                    suffixes.append(str(value))
            except Exception:
                pass
        if suffixes:
            try:
                from .decks.record.model import live_related_names

                try:
                    app = getattr(self, "app", None)  # type: ignore[attr-defined]
                except Exception:
                    app = None
                owner = app if app is not None else self
                try:
                    agents = getattr(owner, "_agents_with_children", None)
                except Exception:
                    agents = None
                if agents is None:
                    try:
                        agents = getattr(owner, "_agents", None)
                    except Exception:
                        agents = None
                kwargs["related_live_names"] = live_related_names(agents, suffixes)
            except Exception:
                pass
        return kwargs

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
                if getattr(agent, "_archive_read_only", False):
                    try:
                        availability = probe_tools_deck(
                            agent, attempt_number=attempt_number
                        )
                    except Exception:
                        availability = DeckAvailability(False, 0)
                    if not availability.has_content:
                        from ..models.agent_archive_reader import (
                            ARCHIVE_MISSING_TOOLS,
                            titled_archive_card,
                        )

                        body = titled_archive_card(ARCHIVE_MISSING_TOOLS)
                        for view in (
                            getattr(panel, "tools_view", None),
                            getattr(panel, "tool_runs_view", None),
                        ):
                            updater = getattr(view, "update", None)
                            if callable(updater):
                                try:
                                    updater(body)
                                except Exception:
                                    pass
            elif panel.deck is DeckId.FINAL:
                # Every FINAL panel paints its own view; the shared
                # stat-signature cache makes duplicates instant.
                try:
                    preferred = self._final_preferred_card(panel)
                except Exception:
                    preferred = None
                if getattr(agent, "_archive_read_only", False):
                    try:
                        availability = probe_final_deck(
                            agent, attempt_number=attempt_number
                        )
                    except Exception:
                        availability = DeckAvailability(False, 0)
                    if not availability.has_content:
                        from ..models.agent_archive_reader import (
                            ARCHIVE_MISSING_FINAL,
                            titled_archive_card,
                        )

                        updater = getattr(panel.final_view, "update", None)
                        if callable(updater):
                            try:
                                updater(titled_archive_card(ARCHIVE_MISSING_FINAL))
                            except Exception:
                                pass
                        continue
                try:
                    panel.final_view.update_display(
                        agent,
                        attempt_number=attempt_number,
                        generation=self._agent_detail_generation,
                        preferred_card=preferred,
                    )
                except Exception:
                    pass
            elif panel.deck is DeckId.RECORD:
                # Every RECORD panel paints its own view; the shared
                # subject-signature cache makes duplicates instant.
                try:
                    preferred = self._record_preferred_card(panel)
                except Exception:
                    preferred = None
                try:
                    panel.record_view.update_display(
                        agent,
                        attempt_number=attempt_number,
                        generation=self._agent_detail_generation,
                        preferred_card=preferred,
                        **self._record_display_kwargs(agent),
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

    def _record_preferred_card(self, panel: Any) -> str | None:
        """Return the panel's sticky RECORD card from area state, if any."""
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            index = panel.panel_index
            return area.state.panels[index].preferred_card_for(DeckId.RECORD)
        except Exception:
            return None

    def show_record_subject(self, subject: Any) -> None:
        """Paint every visible RECORD panel from a light-row subject.

        Unreadable Archive entries and container rows have no hydrated
        Agent. RECORD stays available; other decks are left on their
        titled cards.
        """
        clear_landing = getattr(self, "_clear_main_context_landing", None)
        if callable(clear_landing):
            clear_landing()
        self._current_record_subject = subject
        try:
            area = self.deck_area  # type: ignore[attr-defined]
            panels = area.visible_panels()
        except Exception:
            return
        generation = self._agent_detail_generation
        for panel in panels:
            try:
                availability = dict(getattr(panel, "_availability", {}) or {})
                availability[DeckId.RECORD] = DeckAvailability(True, None)
                panel.set_availability(availability)
            except Exception:
                pass
            if panel.deck is not DeckId.RECORD:
                try:
                    panel.refresh_chrome()
                except Exception:
                    pass
                continue
            try:
                preferred = self._record_preferred_card(panel)
            except Exception:
                preferred = None
            try:
                panel.record_view.show_subject(
                    subject, generation=generation, preferred_card=preferred
                )
            except Exception:
                pass
            try:
                panel.refresh_chrome()
            except Exception:
                pass

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
                record_open = getattr(self, "_current_record_subject", None) is not None
                availability = {
                    DeckId.MAIN: DeckAvailability(
                        bool(self._main_deck_document.cards),
                        len(self._main_deck_document.cards),
                    ),
                    DeckId.FILES: DeckAvailability(False, 0),
                    DeckId.TOOLS: DeckAvailability(False, 0),
                    DeckId.FINAL: DeckAvailability(False, 0),
                    DeckId.RECORD: (
                        DeckAvailability(True, None)
                        if record_open
                        else DeckAvailability(False, 0)
                    ),
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
                    DeckId.RECORD: probe_record_deck(
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
        request = getattr(self, "_main_context_landing", None)
        if request is not None and request.identity != agent.identity:
            self._clear_main_context_landing()  # type: ignore[attr-defined]
        prev_agent = self._current_agent
        self._current_agent = agent
        self._current_record_subject = None
        self._tribe_document_complete = False  # type: ignore[attr-defined]
        self._current_attempt_number = attempt_number
        if prev_agent is not None and prev_agent.identity != agent.identity:
            self._main_deck_document = EMPTY_MAIN_DOCUMENT
        self._update_main_source(agent, attempt_number)  # type: ignore[attr-defined]
        self._deck_refresh_views(agent, stale_threshold_seconds, attempt_number)
        self._deck_refresh_availability()

    def _deck_show_empty(self) -> None:
        from ._agent_detail_helpers import agent_prompt_panel_type  # noqa: F401

        clear_landing = getattr(self, "_clear_main_context_landing", None)
        if callable(clear_landing):
            clear_landing()
        self._agent_detail_generation += 1
        self._current_agent = None
        self._current_record_subject = None
        self._current_tribe_identity = None
        self._tribe_document_complete = False  # type: ignore[attr-defined]
        self._current_attempt_number = None
        try:
            source = self._deck_source_panel()  # type: ignore[attr-defined]
            source.show_empty()
        except Exception:
            pass
        try:
            # Push an empty Main document unconditionally: the Main sink
            # dedups on the prompt-source digest, so without this a titled
            # card pushed straight into the Main panels (for example the
            # Archive loading card) survives the return to empty.
            self._on_main_document("", False, None)  # type: ignore[attr-defined]
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
                    panel.record_view.show_empty()
                except Exception:
                    pass
                try:
                    panel.set_availability(
                        {
                            DeckId.MAIN: DeckAvailability(False, 0),
                            DeckId.FILES: DeckAvailability(False, 0),
                            DeckId.TOOLS: DeckAvailability(False, 0),
                            DeckId.FINAL: DeckAvailability(False, 0),
                            DeckId.RECORD: DeckAvailability(False, 0),
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
        clear_landing = getattr(self, "_clear_main_context_landing", None)
        if callable(clear_landing):
            clear_landing()
        self._agent_detail_generation += 1
        self._current_agent = None
        self._current_record_subject = None
        self._current_tribe_identity = snapshot.container_identity
        self._tribe_document_complete = not cheap  # type: ignore[attr-defined]
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
                    panel.record_view.show_empty()
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
                            DeckId.RECORD: DeckAvailability(False, 0),
                        }
                    )
                except Exception:
                    pass
        except Exception:
            pass


__all__ = ["AgentDetailDeckRefreshMixin"]

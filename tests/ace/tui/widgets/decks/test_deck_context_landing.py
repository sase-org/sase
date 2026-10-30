"""Pilot coverage for stopped-agent Context landings."""

from __future__ import annotations

from typing import Any

import pytest
from rich.text import Text
from textual.containers import VerticalScroll

from sase.ace.testing import wait_for
from sase.ace.tui.agent_decks_settings import AgentDecksSettings
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.card_part import CONTEXT_CARD_ID, reply_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout, DeckView, RenderMode
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets.decks.test_deck_action_targets import _DetailApp
from tests.ace.tui.widgets.decks.test_deck_view_main_pilot import (
    _document,
    _reply_card,
)


def _agent(label: str) -> Any:
    return make_agent(
        cl_name=f"context-{label}",
        raw_suffix=label,
        status="DONE",
    )


def _main_doc(detail: AgentDetail, agent: Any) -> MainDeckDocument:
    return _document(
        detail.metadata_identity,
        _reply_card(6, lines_per_block=40),
        digest=f"context-landing-{agent.cl_name}",
    )


async def _show_agent(pilot: Any, detail: AgentDetail, agent: Any) -> None:
    detail.update_display(agent)
    await pilot.pause()
    detail._deliver_main_document(_main_doc(detail, agent))
    await pilot.pause()


def _scroll(panel: Any) -> VerticalScroll:
    return panel.query_one(
        f"#agent-deck-panel-{panel.panel_index}-main-scroll", VerticalScroll
    )


async def _set_view(
    pilot: Any, detail: AgentDetail, panel: Any, view: DeckView
) -> None:
    assert detail.set_focused_deck_view(view)
    await wait_for(pilot, lambda: panel.effective_layout(DeckId.MAIN) is view)
    render_mode = RenderMode.SPREAD if view is DeckView.SPREAD else RenderMode.PAGED
    await wait_for(pilot, lambda: panel.main_view.render_mode is render_mode)
    await wait_for(
        pilot,
        lambda: (
            int(getattr(panel, "_main_view_applied_generation", 0))
            >= int(getattr(panel, "_view_generation", 0))
        ),
    )
    await pilot.pause()


async def test_context_landing_focuses_visible_main_or_switches_focused_panel() -> None:
    app = _DetailApp()
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _agent("focus")
        await _show_agent(pilot, detail, agent)
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        area = detail.deck_area
        detail.show_deck(1, DeckId.FILES)
        detail.toggle_deck_focus()
        await pilot.pause()
        text_focus = app.focused

        detail.request_main_context_landing(agent.identity)
        await pilot.pause()
        assert area.state.focused == 0
        assert area.panel(0).deck is DeckId.MAIN
        assert area.panel(1).deck is DeckId.FILES
        assert app.focused is text_focus

        detail.show_deck(0, DeckId.FILES)
        detail.show_deck(1, DeckId.TOOLS)
        detail.toggle_deck_focus()
        await pilot.pause()
        assert area.state.focused == 1
        assert area.panels_showing(DeckId.MAIN) == ()
        detail.request_main_context_landing(agent.identity)
        await pilot.pause()
        assert area.state.focused == 1
        assert area.panel(1).deck is DeckId.MAIN


async def test_same_subject_paged_landing_makes_context_sticky_and_resets_scroll() -> (
    None
):
    app = _DetailApp()
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _agent("paged")
        await _show_agent(pilot, detail, agent)
        panel = detail.deck_area.panel(0)
        await _set_view(pilot, detail, panel, DeckView.PAGE_CARDS)
        assert detail.cycle_focused_deck_card(1) == "reply"
        await pilot.pause()
        assert panel.main_view.active_card_id == "reply"
        scroll = _scroll(panel)
        scroll.scroll_to(y=25, animate=False, immediate=True)
        await pilot.pause()
        assert int(scroll.scroll_y) > 0

        detail.request_main_context_landing(agent.identity)
        await pilot.pause()
        assert panel.main_view.active_card_id == CONTEXT_CARD_ID
        assert scroll.scroll_y == 0
        assert (
            detail.deck_area.state.panels[0].preferred_card_for(DeckId.MAIN)
            == CONTEXT_CARD_ID
        )


async def test_same_subject_spread_landing_releases_bottom_pin() -> None:
    app = _DetailApp()
    app._agent_decks_settings = AgentDecksSettings(
        spread_max_screens=1000, block_spread_max_screens=1000
    )
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _agent("spread")
        await _show_agent(pilot, detail, agent)
        panel = detail.deck_area.panel(0)
        await _set_view(pilot, detail, panel, DeckView.SPREAD)
        detail.set_deck_preferred_card(0, "reply", DeckId.MAIN)
        await pilot.pause()
        scroll = _scroll(panel)
        panel.main_view.pin_to_bottom()
        await wait_for(pilot, lambda: panel.main_view.is_pinned_to_bottom)
        await wait_for(pilot, lambda: int(scroll.scroll_y) > 0)

        detail.request_main_context_landing(agent.identity)
        await wait_for(pilot, lambda: int(scroll.scroll_y) == 0)
        assert panel.main_view.is_pinned_to_bottom is False
        assert panel.main_view.active_card_id == CONTEXT_CARD_ID


@pytest.mark.parametrize("view", [DeckView.PAGE_CARDS, DeckView.SPREAD])
async def test_new_subject_landing_survives_redelivery(view: DeckView) -> None:
    app = _DetailApp()
    app._agent_decks_settings = AgentDecksSettings(
        spread_max_screens=1000, block_spread_max_screens=1000
    )
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent_a = _agent(f"a-{view.value}")
        agent_b = _agent(f"b-{view.value}")
        await _show_agent(pilot, detail, agent_a)
        panel = detail.deck_area.panel(0)
        await _set_view(pilot, detail, panel, view)
        detail.set_deck_preferred_card(0, "reply", DeckId.MAIN)
        await pilot.pause()

        detail.request_main_context_landing(agent_b.identity)
        detail.update_display(agent_b)
        await pilot.pause()
        doc_b = _main_doc(detail, agent_b)
        detail._deliver_main_document(doc_b)
        await pilot.pause()
        assert panel.main_view.active_card_id == CONTEXT_CARD_ID
        assert (
            detail.deck_area.state.panels[0].preferred_card_for(DeckId.MAIN)
            == CONTEXT_CARD_ID
        )

        detail._deliver_main_document(doc_b)
        await pilot.pause()
        assert panel.main_view.active_card_id == CONTEXT_CARD_ID


async def test_card_cycle_clears_landing_and_updates_sticky_card() -> None:
    app = _DetailApp()
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _agent("cycle")
        await _show_agent(pilot, detail, agent)
        detail.request_main_context_landing(agent.identity)

        assert detail.cycle_focused_deck_card(1) == "reply"
        assert detail._main_context_landing is None
        assert (
            detail.deck_area.state.panels[0].preferred_card_for(DeckId.MAIN) == "reply"
        )


async def test_subject_change_clears_stale_landing() -> None:
    app = _DetailApp()
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent_a = _agent("stale-a")
        agent_b = _agent("stale-b")
        agent_c = _agent("stale-c")
        await _show_agent(pilot, detail, agent_a)

        detail.request_main_context_landing(agent_b.identity)
        detail.update_display(agent_c)
        await pilot.pause()
        assert detail._main_context_landing is None
        detail.set_deck_preferred_card(0, "reply", DeckId.MAIN)
        detail.update_display(agent_b)
        await pilot.pause()
        detail._deliver_main_document(_main_doc(detail, agent_b))
        await pilot.pause()
        assert detail.deck_area.panel(0).main_view.active_card_id == "reply"


async def test_landing_falls_back_to_first_card_without_context() -> None:
    app = _DetailApp()
    async with app.run_test(size=(110, 34)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = _agent("no-context")
        await _show_agent(pilot, detail, agent)
        document = MainDeckDocument(
            cards=(reply_card(Text("reply body")),),
            subject=detail.metadata_identity,
            partial=False,
            digest="reply-only",
        )
        detail._deliver_main_document(document)

        detail.request_main_context_landing(agent.identity)
        await pilot.pause()
        assert detail.deck_area.panel(0).main_view.active_card_id == "reply"

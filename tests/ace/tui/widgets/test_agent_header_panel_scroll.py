"""Expanded-header scroll claiming for the Agents tab identity header."""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult

from sase.ace.testing import wait_for
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.agent_header_panel import AgentHeaderPanel
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from tests.ace.tui.widgets._agent_header_panel_shared import (
    LONG_XPROMPT,
    artifact_agent,
    header_panel,
    show_agent,
    show_agent_full,
    solo_agent,
)


class _HeaderScrollNavApp(BasicNavigationMixin, App[None]):
    current_tab = "agents"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def _show_overflowing_expanded(
    detail: AgentDetail, tmp_path: Any, pilot: Any, name: str = "a"
) -> AgentHeaderPanel:
    await show_agent_full(detail, artifact_agent(tmp_path, name, LONG_XPROMPT), pilot)
    panel = header_panel(detail)
    if not panel.is_expanded:
        assert detail.toggle_header_expanded() is True
        await pilot.pause()
    assert panel.is_header_scrollable() is True
    assert int(panel.max_scroll_y) > 0
    return panel


async def test_expanded_overflowing_header_claims_half_page_scroll(
    tmp_path: Any,
) -> None:
    app = _HeaderScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = await _show_overflowing_expanded(detail, tmp_path, pilot)
        deck_scroll = detail.deck_area.focused_panel().active_scroll()
        deck_calls: list[tuple[Any, ...]] = []
        original_deck_scroll = deck_scroll.scroll_relative

        def _record_deck(*args: Any, **kwargs: Any) -> None:
            deck_calls.append((args, kwargs))
            return original_deck_scroll(*args, **kwargs)

        deck_scroll.scroll_relative = _record_deck  # type: ignore[method-assign]
        main_view = detail.deck_area.panel(0).main_view
        main_view.pin_to_bottom()
        assert bool(main_view.is_pinned_to_bottom) is True
        await wait_for(pilot, lambda: main_view.is_bottom_pin_settled)
        deck_y = float(deck_scroll.scroll_y)
        header_h = int(panel.scrollable_content_region.height)
        expected_step = max(1, header_h // 2)
        assert expected_step >= 1

        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(panel.scroll_y) == float(expected_step)
        assert float(deck_scroll.scroll_y) == deck_y
        assert deck_calls == []
        assert bool(main_view.is_pinned_to_bottom) is True

        app.action_scroll_detail_up()
        await pilot.pause()
        assert float(panel.scroll_y) == 0.0
        assert float(deck_scroll.scroll_y) == deck_y
        assert deck_calls == []
        assert bool(main_view.is_pinned_to_bottom) is True


async def test_header_boundary_claims_key_without_moving_deck(
    tmp_path: Any,
) -> None:
    app = _HeaderScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = await _show_overflowing_expanded(detail, tmp_path, pilot)
        deck_scroll = detail.deck_area.focused_panel().active_scroll()
        main_view = detail.deck_area.panel(0).main_view
        main_view.pin_to_bottom()

        panel.scroll_to(y=float(panel.max_scroll_y), animate=False)
        await pilot.pause()
        assert float(panel.scroll_y) == float(panel.max_scroll_y)
        deck_y = float(deck_scroll.scroll_y)
        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(panel.scroll_y) == float(panel.max_scroll_y)
        assert float(deck_scroll.scroll_y) == deck_y
        assert bool(main_view.is_pinned_to_bottom) is True

        panel.scroll_to(y=0, animate=False)
        await pilot.pause()
        assert float(panel.scroll_y) == 0.0
        app.action_scroll_detail_up()
        await pilot.pause()
        assert float(panel.scroll_y) == 0.0
        assert float(deck_scroll.scroll_y) == deck_y
        assert bool(main_view.is_pinned_to_bottom) is True


async def test_hint_expanded_header_claims_scroll(tmp_path: Any) -> None:
    app = _HeaderScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = artifact_agent(tmp_path, "a", LONG_XPROMPT)
        await show_agent_full(detail, agent, pilot)
        panel = header_panel(detail)
        assert not panel.is_expanded
        assert panel.is_header_scrollable() is False
        detail.update_display_with_hints(agent)
        await pilot.pause()
        assert not panel.is_expanded
        assert panel.is_header_scrollable() is False
        assert detail.toggle_header_expanded() is True
        await pilot.pause()
        assert panel.is_header_scrollable() is True
        assert int(panel.max_scroll_y) > 0
        deck_scroll = detail.deck_area.focused_panel().active_scroll()
        deck_y = float(deck_scroll.scroll_y)
        header_h = int(panel.scrollable_content_region.height)
        expected_step = max(1, header_h // 2)

        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(panel.scroll_y) == float(expected_step)
        assert float(deck_scroll.scroll_y) == deck_y


async def test_header_fallback_targets_focused_deck(tmp_path: Any) -> None:
    app = _HeaderScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        # Collapsed but overflowing preview must still fall back to the deck.
        await show_agent_full(
            detail, artifact_agent(tmp_path, "a", LONG_XPROMPT), pilot
        )
        panel = header_panel(detail)
        assert not panel.is_expanded
        assert int(panel.max_scroll_y) > 0
        assert panel.is_header_scrollable() is False
        assert detail.try_scroll_expanded_header(1) is False
        main_view = detail.deck_area.panel(0).main_view
        main_view.pin_to_bottom()
        deck_scroll = detail.deck_area.focused_panel().active_scroll()
        deck_calls: list[tuple[Any, ...]] = []
        original = deck_scroll.scroll_relative

        def _record(*args: Any, **kwargs: Any) -> None:
            deck_calls.append((args, kwargs))
            return original(*args, **kwargs)

        deck_scroll.scroll_relative = _record  # type: ignore[method-assign]
        header_y = float(panel.scroll_y)
        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(panel.scroll_y) == header_y
        assert len(deck_calls) == 1
        assert bool(main_view.is_pinned_to_bottom) is False

        # Expanded but fits without overflow falls back as well.
        await show_agent(detail, solo_agent(), pilot)
        panel = header_panel(detail)
        assert detail.toggle_header_expanded() is True
        await pilot.pause()
        assert int(panel.max_scroll_y) == 0
        assert panel.is_header_scrollable() is False
        assert detail.try_scroll_expanded_header(-1) is False

        # Hidden header falls back as well.
        detail.show_empty()
        await pilot.pause()
        assert panel.has_class("hidden")
        assert panel.is_header_scrollable() is False
        assert detail.try_scroll_expanded_header(1) is False


async def test_short_viewport_header_step_is_at_least_one_row(
    tmp_path: Any,
) -> None:
    app = _HeaderScrollNavApp()
    async with app.run_test(size=(80, 12)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = await _show_overflowing_expanded(detail, tmp_path, pilot)
        header_h = int(panel.scrollable_content_region.height)
        assert header_h <= 1
        expected_step = max(1, header_h // 2)
        assert expected_step == 1
        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(panel.scroll_y) == 1.0


async def test_non_main_focused_deck_header_still_claims(tmp_path: Any) -> None:
    from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout

    app = _HeaderScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = await _show_overflowing_expanded(detail, tmp_path, pilot)
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        detail.show_deck(0, DeckId.MAIN)
        detail.show_deck(1, DeckId.FILES)
        await pilot.pause()
        assert detail.focused_deck() is not DeckId.MAIN
        focused_scroll = detail.deck_area.focused_panel().active_scroll()
        focused_y = float(focused_scroll.scroll_y)
        main_view = detail.deck_area.panel(0).main_view
        main_view.pin_to_bottom()
        header_h = int(panel.scrollable_content_region.height)
        expected_step = max(1, header_h // 2)

        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(panel.scroll_y) == float(expected_step)
        assert float(focused_scroll.scroll_y) == focused_y
        assert bool(main_view.is_pinned_to_bottom) is True

"""Ctrl+D/U scroll claiming for the expanded Agents jump panel."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from textual.app import App, ComposeResult

from sase.ace.testing import wait_for
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.widgets.agent_detail import AgentDetail
from tests.ace.tui.widgets._agent_header_panel_shared import (
    LONG_RAW_PROMPT,
    artifact_agent,
    header_panel,
    show_agent_full,
)
from tests.ace.tui.widgets._agent_jump_panel_helpers import (
    _jump_panel,
    _labeled_map,
    _labeled_map_and_roster,
    _show_agent,
    _solo,
)


class _FooterScrollNavApp(BasicNavigationMixin, App[None]):
    current_tab = "agents"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def _show_both_overflowing(
    detail: AgentDetail, tmp_path: Any, pilot: Any, name: str = "both"
) -> tuple[Any, Any]:
    """Show an artifact agent with both sticky panels expanded and overflowing."""
    await show_agent_full(
        detail, artifact_agent(tmp_path, name, LONG_RAW_PROMPT), pilot
    )
    header = header_panel(detail)
    if not header.is_expanded:
        assert detail.toggle_header_expanded() is True
        await pilot.pause()
    solo = _solo()
    jump_map, roster = _labeled_map_and_roster(
        solo, [f"target-{i:02d}" for i in range(20)]
    )
    detail._on_member_jump_map(jump_map, roster)  # noqa: SLF001
    await pilot.pause()
    footer = _jump_panel(detail)
    if not footer.is_expanded:
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
    # A late debounced publish may clear the injected map; re-inject last.
    detail._on_member_jump_map(jump_map, roster)  # noqa: SLF001
    await pilot.pause()
    if not footer.is_expanded:
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
    assert footer.is_jump_panel_scrollable() is True
    assert int(footer.max_scroll_y) > 0
    assert header.is_header_scrollable() is True
    assert int(header.max_scroll_y) > 0
    return header, footer


async def _show_footer_only(
    detail: AgentDetail, pilot: Any, labels: list[str], name: str = "solo"
) -> Any:
    """Show a solo agent with an expanded footer over ``labels`` targets."""
    del name
    await _show_agent(detail, _solo(), pilot)
    solo = _solo()
    jump_map, roster = _labeled_map_and_roster(solo, labels)
    detail._on_member_jump_map(jump_map, roster)  # noqa: SLF001
    await pilot.pause()
    footer = _jump_panel(detail)
    if not footer.is_expanded:
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
    detail._on_member_jump_map(jump_map, roster)  # noqa: SLF001
    await pilot.pause()
    if not footer.is_expanded:
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
    return footer


def _record_scroll(scroll: Any) -> list[tuple[Any, ...]]:
    """Wrap ``scroll_relative`` on ``scroll`` and return the call log."""
    calls: list[tuple[Any, ...]] = []
    original = scroll.scroll_relative

    def _record(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    scroll.scroll_relative = _record  # type: ignore[method-assign]
    return calls


async def _pin_main_bottom(detail: AgentDetail, pilot: Any) -> Any:
    main_view = detail.deck_area.panel(0).main_view
    main_view.pin_to_bottom()
    assert bool(main_view.is_pinned_to_bottom) is True
    await wait_for(pilot, lambda: main_view.is_bottom_pin_settled)
    return main_view


async def test_expanded_overflowing_footer_claims_half_page_scroll(
    tmp_path: Any,
) -> None:
    app = _FooterScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        _header, footer = await _show_both_overflowing(
            detail, tmp_path, pilot, name="footer-claim"
        )
        deck_scroll = detail.deck_area.focused_panel().active_scroll()
        deck_calls = _record_scroll(deck_scroll)
        main_view = await _pin_main_bottom(detail, pilot)
        deck_y = float(deck_scroll.scroll_y)
        footer_h = int(footer.scrollable_content_region.height)
        expected_step = max(1, footer_h // 2)
        assert expected_step >= 1

        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(footer.scroll_y) == float(expected_step)
        assert float(deck_scroll.scroll_y) == deck_y
        assert deck_calls == []
        assert bool(main_view.is_pinned_to_bottom) is True

        app.action_scroll_detail_up()
        await pilot.pause()
        assert float(footer.scroll_y) == 0.0
        assert float(deck_scroll.scroll_y) == deck_y
        assert deck_calls == []
        assert bool(main_view.is_pinned_to_bottom) is True


async def test_footer_boundary_claims_key_without_moving_deck(
    tmp_path: Any,
) -> None:
    app = _FooterScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        _header, footer = await _show_both_overflowing(
            detail, tmp_path, pilot, name="footer-boundary"
        )
        deck_scroll = detail.deck_area.focused_panel().active_scroll()
        main_view = await _pin_main_bottom(detail, pilot)

        footer.scroll_to(y=float(footer.max_scroll_y), animate=False)
        await pilot.pause()
        assert float(footer.scroll_y) == float(footer.max_scroll_y)
        deck_y = float(deck_scroll.scroll_y)
        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(footer.scroll_y) == float(footer.max_scroll_y)
        assert float(deck_scroll.scroll_y) == deck_y
        assert bool(main_view.is_pinned_to_bottom) is True

        footer.scroll_to(y=0, animate=False)
        await pilot.pause()
        assert float(footer.scroll_y) == 0.0
        app.action_scroll_detail_up()
        await pilot.pause()
        assert float(footer.scroll_y) == 0.0
        assert float(deck_scroll.scroll_y) == deck_y
        assert bool(main_view.is_pinned_to_bottom) is True


async def test_collapsed_overflowing_footer_falls_back_to_deck() -> None:
    app = _FooterScrollNavApp()
    async with app.run_test(size=(80, 12)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        solo = _solo()
        jump_map = _labeled_map(solo, [f"target-{i:02d}" for i in range(12)])
        detail._on_member_jump_map(jump_map, None)  # noqa: SLF001
        await pilot.pause()
        footer = _jump_panel(detail)
        assert not footer.is_expanded
        assert int(footer.max_scroll_y) > 0
        assert footer.is_jump_panel_scrollable() is False
        assert detail.try_scroll_expanded_jump_panel(1) is False
        deck_scroll = detail.deck_area.focused_panel().active_scroll()
        deck_calls = _record_scroll(deck_scroll)
        footer_y = float(footer.scroll_y)
        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(footer.scroll_y) == footer_y
        assert len(deck_calls) == 1


async def test_expanded_fitting_footer_falls_back_to_deck() -> None:
    app = _FooterScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        footer = await _show_footer_only(detail, pilot, ["aa", "bb"])
        assert int(footer.max_scroll_y) == 0
        assert footer.is_jump_panel_scrollable() is False
        assert detail.try_scroll_expanded_jump_panel(1) is False
        deck_scroll = detail.deck_area.focused_panel().active_scroll()
        deck_calls = _record_scroll(deck_scroll)
        app.action_scroll_detail_down()
        await pilot.pause()
        assert len(deck_calls) == 1


async def test_hidden_footer_is_not_scrollable() -> None:
    app = _FooterScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        footer = await _show_footer_only(detail, pilot, ["aa", "bb"])
        detail.show_empty()
        await pilot.pause()
        assert footer.has_class("hidden")
        assert footer.is_jump_panel_scrollable() is False
        assert detail.try_scroll_expanded_jump_panel(1) is False


async def test_narrowed_footer_is_not_scrollable(tmp_path: Any) -> None:
    app = _FooterScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        _header, footer = await _show_both_overflowing(
            detail, tmp_path, pilot, name="footer-narrowed"
        )
        assert footer.is_jump_panel_scrollable() is True
        footer.set_pending_prefix("1")
        await pilot.pause()
        assert footer.is_jump_panel_scrollable() is False
        assert detail.try_scroll_expanded_jump_panel(1) is False


async def test_footer_wins_over_header(tmp_path: Any) -> None:
    app = _FooterScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        header, footer = await _show_both_overflowing(
            detail, tmp_path, pilot, name="footer-priority"
        )
        deck_scroll = detail.deck_area.focused_panel().active_scroll()

        footer_h = int(footer.scrollable_content_region.height)
        expected_footer_step = max(1, footer_h // 2)
        header_y = float(header.scroll_y)
        deck_y = float(deck_scroll.scroll_y)
        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(footer.scroll_y) == float(expected_footer_step)
        assert float(header.scroll_y) == header_y
        assert float(deck_scroll.scroll_y) == deck_y

        app.action_scroll_detail_up()
        await pilot.pause()
        assert float(footer.scroll_y) == 0.0
        assert float(header.scroll_y) == header_y

        assert detail.toggle_jump_panel_expanded() is False
        await pilot.pause()
        assert footer.is_jump_panel_scrollable() is False
        header_h = int(header.scrollable_content_region.height)
        expected_header_step = max(1, header_h // 2)
        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(header.scroll_y) == float(expected_header_step)


async def test_footer_at_boundary_still_wins_over_header(tmp_path: Any) -> None:
    app = _FooterScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        header, footer = await _show_both_overflowing(
            detail, tmp_path, pilot, name="footer-boundary-wins"
        )
        footer.scroll_to(y=float(footer.max_scroll_y), animate=False)
        await pilot.pause()
        assert float(footer.scroll_y) == float(footer.max_scroll_y)
        header_y = float(header.scroll_y)
        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(footer.scroll_y) == float(footer.max_scroll_y)
        assert float(header.scroll_y) == header_y


async def test_header_claims_when_footer_fits(tmp_path: Any) -> None:
    app = _FooterScrollNavApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await show_agent_full(
            detail, artifact_agent(tmp_path, "hdr-fits", LONG_RAW_PROMPT), pilot
        )
        header = header_panel(detail)
        if not header.is_expanded:
            assert detail.toggle_header_expanded() is True
            await pilot.pause()
        assert header.is_header_scrollable() is True
        solo = _solo()
        jump_map, roster = _labeled_map_and_roster(solo, ["aa", "bb"])
        detail._on_member_jump_map(jump_map, roster)  # noqa: SLF001
        await pilot.pause()
        footer = _jump_panel(detail)
        if not footer.is_expanded:
            assert detail.toggle_jump_panel_expanded() is True
            await pilot.pause()
        detail._on_member_jump_map(jump_map, roster)  # noqa: SLF001
        await pilot.pause()
        assert footer.is_jump_panel_scrollable() is False
        deck_scroll = detail.deck_area.focused_panel().active_scroll()
        deck_y = float(deck_scroll.scroll_y)
        header_h = int(header.scrollable_content_region.height)
        expected_step = max(1, header_h // 2)
        app.action_scroll_detail_down()
        await pilot.pause()
        assert float(header.scroll_y) == float(expected_step)
        assert float(deck_scroll.scroll_y) == deck_y


async def test_metadata_search_routing_prefers_footer(tmp_path: Any) -> None:
    from sase.ace.tui.actions.agents._metadata_search import (
        AgentMetadataSearchMixin,
    )
    from sase.ace.tui.keymaps import split_key_alternatives
    from sase.ace.tui.widgets.agent_detail import AgentDetail as DetailCls
    from textual.app import App as TextualApp
    from textual.app import ComposeResult as TextualComposeResult

    class _DetailApp(TextualApp[None]):
        def compose(self) -> TextualComposeResult:
            yield DetailCls(id="agent-detail-panel")

    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", DetailCls)
        header, footer = await _show_both_overflowing(
            detail, tmp_path, pilot, name="search-routing"
        )
        registry = SimpleNamespace(
            app=SimpleNamespace(
                scroll_detail_down="ctrl+d",
                scroll_detail_up="ctrl+u",
            )
        )
        down_keys = split_key_alternatives("ctrl+d")
        up_keys = split_key_alternatives("ctrl+u")
        assert down_keys and up_keys
        host = SimpleNamespace(
            _keymap_registry=registry,
            _agent_detail=lambda: detail,
        )
        footer_h = int(footer.scrollable_content_region.height)
        expected_step = max(1, footer_h // 2)
        header_y = float(header.scroll_y)
        assert (
            AgentMetadataSearchMixin._try_scroll_expanded_sticky_panel_for_key(
                host, "ctrl+d"
            )
            is True
        )
        await pilot.pause()
        assert float(footer.scroll_y) == float(expected_step)
        assert float(header.scroll_y) == header_y
        assert (
            AgentMetadataSearchMixin._try_scroll_expanded_sticky_panel_for_key(
                host, "x"
            )
            is False
        )

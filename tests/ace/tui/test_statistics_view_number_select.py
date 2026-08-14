"""Number-prefix dispatch coverage for Admin Center Statistics views."""

from __future__ import annotations

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.statistics_pane_data import (
    StatisticsView,
    VIEW_LABELS,
)
from sase.stats.ranges import StatsRange

from tests.ace.tui._statistics_pane_helpers import (
    _open_statistics,
    _patch_center,
)


async def test_number_prefix_selects_second_and_seventh_views(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal, pane = await _open_statistics(page)

        await page.press("0")
        assert pane._pending_view_select is True
        assert (
            pane.query_one("#statistics-hints", Static).render().plain
            == "0… press 1-7 to select a view"
        )
        await page.press("2")
        await page.wait_for(lambda _state: pane._view == "runners")
        assert modal._active_tab == "statistics"
        assert pane._pending_view_select is False

        await page.press("0", "7")
        await page.wait_for(lambda _state: pane._view == "plans_questions")
        assert modal._active_tab == "statistics"
        assert pane._pending_view_select is False


async def test_number_prefix_ignores_out_of_range_digit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal, pane = await _open_statistics(page)

        await page.press("0", "8")
        await page.pause()

        assert modal._active_tab == "statistics"
        assert pane._view == "overview"
        assert pane._pending_view_select is False


async def test_bare_digit_keeps_switching_admin_center_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal, pane = await _open_statistics(page)

        await page.press("4")
        await page.wait_for(lambda _state: modal._active_tab == "projects")

        assert pane._view == "overview"
        assert pane._pending_view_select is False


async def test_repeated_prefix_rearms_before_view_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal, pane = await _open_statistics(page)

        await page.press("0", "0", "2")
        await page.wait_for(lambda _state: pane._view == "runners")

        assert modal._active_tab == "statistics"
        assert pane._pending_view_select is False


@pytest.mark.parametrize("close_key", ("q", "escape"))
async def test_non_digit_cancels_prefix_and_continues_to_modal(
    monkeypatch: pytest.MonkeyPatch,
    close_key: str,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        await page.press("0", close_key)
        await page.wait_for(lambda _state: len(page.app.screen_stack) == 1)

        assert pane._pending_view_select is False
        assert not isinstance(page.app.screen, ConfigCenterModal)


async def test_range_input_keeps_prefix_digit_as_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        await page.press("c")
        custom_input = pane.query_one("#statistics-custom-range", Input)
        await page.press("0")

        assert custom_input.has_focus
        assert custom_input.value == "0"
        assert pane._pending_view_select is False


async def test_jump_key_then_digit_selects_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal, pane = await _open_statistics(page)

        await page.press("apostrophe")
        assert pane._pending_view_select is True
        await page.press("3")
        await page.wait_for(lambda _state: pane._view == "projects")

        assert modal._active_tab == "statistics"
        assert pane._pending_view_select is False


@pytest.mark.parametrize("close_key", ("q", "escape"))
async def test_jump_key_non_digit_cancels_prefix_and_continues_to_modal(
    monkeypatch: pytest.MonkeyPatch,
    close_key: str,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        await page.press("apostrophe", close_key)
        await page.wait_for(lambda _state: len(page.app.screen_stack) == 1)

        assert pane._pending_view_select is False
        assert not isinstance(page.app.screen, ConfigCenterModal)


async def test_repeated_jump_key_cancels_armed_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        await page.press("apostrophe")
        assert pane._pending_view_select is True
        await page.press("apostrophe")
        await page.pause()

        assert pane._pending_view_select is False
        assert pane._view == "overview"


async def test_range_input_keeps_jump_key_as_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        await page.press("c")
        custom_input = pane.query_one("#statistics-custom-range", Input)
        await page.press("apostrophe")

        assert custom_input.has_focus
        assert custom_input.value == "'"
        assert pane._pending_view_select is False


async def test_configured_prefix_arms_the_same_number_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)
    registry = load_keymap_registry({"keymaps": {"statistics": {"select_view": "f4"}}})

    async with AcePage() as page:
        page.app._keymap_registry = registry
        modal, pane = await _open_statistics(page)

        await page.press("f4")
        hints = pane.query_one("#statistics-hints", Static).render().plain
        assert hints == "f4… press 1-7 to select a view"
        await page.press("2")
        await page.wait_for(lambda _state: pane._view == "runners")

        assert modal._active_tab == "statistics"
        assert VIEW_LABELS[pane._view] == "Runners"
        assert pane._pending_view_select is False

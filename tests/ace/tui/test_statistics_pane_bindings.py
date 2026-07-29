"""Keybinding coverage for the Statistics pane."""

from __future__ import annotations

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui.keymaps import load_keymap_registry, statistics_help_bindings
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.statistics_help_modal import StatisticsHelpModal
from sase.ace.tui.modals.statistics_pane_data import StatisticsView
from sase.stats.query import RuntimeGroupBy
from sase.stats.ranges import StatsRange

from tests.ace.tui._statistics_pane_helpers import (
    _open_statistics,
    _patch_center,
    _scope_plain,
)


async def test_configured_bindings_dispatch_and_render_effective_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)
    registry = load_keymap_registry(
        {
            "keymaps": {
                "statistics": {
                    "prev_view": "f12",
                    "next_view": "f11",
                    "cycle_range": "f10",
                    "cycle_range_reverse": "f9",
                    "custom_range": "f8",
                    "cycle_group": "f7",
                    "cycle_project_filter": "f6",
                    "cycle_project_filter_reverse": "f1",
                    "focus_xprompt": "home",
                    "clear_xprompt_focus": "end",
                    "scroll_down": "f5",
                    "scroll_up": "f4",
                    "refresh": "f3",
                    "help": "f2",
                }
            }
        }
    )

    assert statistics_help_bindings(registry.statistics) == [
        ("f12", "Previous View"),
        ("f11", "Next View"),
        ("f10", "Time Range"),
        ("f9", "Previous Time Range"),
        ("f8", "Custom Range"),
        ("f7", "Group By"),
        ("f6", "Project Filter"),
        ("f1", "Previous Project Filter"),
        ("home", "Focus XPrompt"),
        ("end", "Clear XPrompt Focus"),
        ("f5", "Scroll Down"),
        ("f4", "Scroll Up"),
        ("f3", "Refresh"),
        ("f2", "Help"),
    ]

    async with AcePage() as page:
        page.app._keymap_registry = registry
        _, pane = await _open_statistics(page)

        hints = pane.query_one("#statistics-hints", Static).render().plain
        assert hints == (
            "f12 / f11 views   f8 custom range   f5/f4 scroll   f3 refresh   f2 help"
        )
        assert _scope_plain(pane, "range").startswith(" f10/f9  Range ")
        assert pane.query_one("#statistics-scope-group", Static).display is False
        assert _scope_plain(pane, "project").startswith(" f6/f1  Project ")

        await page.press("f1")
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        assert pane._project_filter == "core"
        assert calls[-1][3] == "core"

        await page.press("f6")
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)
        assert pane._project_filter is None
        assert calls[-1][3] is None

        await page.press("f9")
        await page.wait_for(lambda _state: len(calls) == 4 and not pane._loading)
        assert pane._preset_key == "24h"

        await page.press("f11", "f11", "f11", "f7")
        await page.wait_for(
            lambda _state: (
                pane._view == "projects" and pane._projects_group_by == "changespec"
            )
        )
        assert pane.query_one("#statistics-scope-group", Static).display is True
        assert _scope_plain(pane, "group").startswith(" f7  Group ")
        assert len(calls) == 4

        pane._set_view("runners")
        scroll = pane.query_one("#statistics-body-scroll", VerticalScroll)
        await page.wait_for(lambda _state: scroll.max_scroll_y > 0)
        await page.press("f5")
        await page.wait_for(lambda _state: scroll.scroll_y > 0)
        moved = scroll.scroll_y
        await page.press("f4")
        await page.wait_for(lambda _state: scroll.scroll_y < moved)
        assert pane._view == "runners"
        assert len(calls) == 4


async def test_default_half_page_scroll_does_not_reload_or_capture_range_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("runners")
        scroll = pane.query_one("#statistics-body-scroll", VerticalScroll)
        await page.wait_for(lambda _state: scroll.max_scroll_y > 0)

        await page.press("ctrl+d")
        await page.wait_for(lambda _state: scroll.scroll_y > 0)
        moved = scroll.scroll_y
        await page.press("ctrl+u")
        await page.wait_for(lambda _state: scroll.scroll_y < moved)
        assert scroll.scroll_y == 0
        assert pane._view == "runners"
        assert len(calls) == 1

        await page.press("c")
        custom_input = pane.query_one("#statistics-custom-range", Input)
        assert custom_input.has_focus
        await page.pause()
        before_input_key = scroll.scroll_y
        await page.press("ctrl+d", "ctrl+u")
        await page.pause()
        assert scroll.scroll_y == before_input_key
        assert custom_input.has_focus
        assert len(calls) == 1


async def test_statistics_help_opens_and_closes_from_configured_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)
    registry = load_keymap_registry({"keymaps": {"statistics": {"help": "f5"}}})

    async with AcePage() as page:
        page.app._keymap_registry = registry
        _, pane = await _open_statistics(page)

        await page.press("f5")
        await page.expect_modal("StatisticsHelpModal")
        assert isinstance(page.app.screen, StatisticsHelpModal)
        footer = page.app.screen.query_one("#statistics-help-footer", Static)
        assert "f5/q/Esc close" in footer.render().plain

        await page.press("f5")
        await page.expect_modal("ConfigCenterModal")
        assert pane.is_mounted


async def test_statistics_bindings_are_inactive_on_other_admin_center_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, RuntimeGroupBy, str | None]] = []
    _patch_center(monkeypatch, calls)
    registry = load_keymap_registry(
        {
            "keymaps": {
                "statistics": {
                    "cycle_range_reverse": "f12",
                    "scroll_down": "f10",
                    "scroll_up": "f9",
                    "help": "f5",
                }
            }
        }
    )

    async with AcePage() as page:
        page.app._keymap_registry = registry
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        assert not modal.query("#statistics")

        await page.press("f12")
        await page.press("f10")
        await page.press("f9")
        await page.press("f5")
        await page.pause()

        assert modal._active_tab == "config"
        assert not modal.query("#statistics")
        assert calls == []
        assert isinstance(page.app.screen, ConfigCenterModal)

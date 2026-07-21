"""Keybinding coverage for the Statistics pane."""

from __future__ import annotations

import pytest
from textual.widgets import Static

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
                    "refresh": "f5",
                    "help": "f4",
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
        ("f5", "Refresh"),
        ("f4", "Help"),
    ]

    async with AcePage() as page:
        page.app._keymap_registry = registry
        _, pane = await _open_statistics(page)

        hints = pane.query_one("#statistics-hints", Static).render().plain
        assert hints == "f12 / f11 views   f8 custom range   f5 refresh   f4 help"
        assert _scope_plain(pane, "range").startswith(" f10/f9  Range ")
        assert _scope_plain(pane, "group").startswith(" f7  Group ")
        assert _scope_plain(pane, "project").startswith(" f6  Project ")
        await page.press("f9")
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        assert pane._preset_key == "24h"

        await page.press("f11", "f11", "f11", "f7")
        await page.wait_for(
            lambda _state: (
                pane._view == "projects" and pane._projects_group_by == "changespec"
            )
        )
        assert len(calls) == 2


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
        {"keymaps": {"statistics": {"cycle_range_reverse": "f12", "help": "f5"}}}
    )

    async with AcePage() as page:
        page.app._keymap_registry = registry
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        assert not modal.query("#statistics")

        await page.press("f12")
        await page.press("f5")
        await page.pause()

        assert modal._active_tab == "config"
        assert not modal.query("#statistics")
        assert calls == []
        assert isinstance(page.app.screen, ConfigCenterModal)

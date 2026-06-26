"""Load, grouping, filtering, and tab-cycle tests for the Plugins pane."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.plugins.catalog import PluginCatalog
from tests.ace.tui._plugins_browser_pane_helpers import (
    _NOW,
    _catalog,
    _open_plugins_pane,
    _option_labels,
    _patch_catalog,
    _patch_other_panes,
)


async def test_plugins_pane_loads_and_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        # Both section headers and every plugin row are present.
        labels = _option_labels(pane)
        assert any("Built-in" in label for label in labels)
        assert any("Community" in label for label in labels)
        assert any("github" in label for label in labels)
        assert any("acme" in label for label in labels)
        # The status placeholder is hidden and the list is visible.
        assert pane.query_one("#plugins-list").display is True
        assert pane.query_one("#plugins-status").display is False
        # A non-header row is auto-highlighted.
        option_list = pane.query_one("#plugins-list", OptionList)
        assert option_list.highlighted is not None
        highlighted = option_list.get_option_at_index(option_list.highlighted)
        assert highlighted.id is not None
        assert not str(highlighted.id).startswith("__header__")


async def test_plugins_pane_summary_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        summary = pane._summary_text()
        assert "4 plugins" in summary
        assert "2 installed" in summary
        assert "1 updates available" in summary
        assert "just now" in summary


async def test_plugins_pane_shows_update_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        labels = _option_labels(pane)
        github_row = next(label for label in labels if "github" in label)
        # Installed with an available update: version arrow + update glyph.
        assert "v1.2.0 → v1.3.0" in github_row
        assert "↑" in github_row
        nvim_row = next(label for label in labels if "nvim" in label)
        assert "latest v2.0.0" in nvim_row


async def test_plugins_pane_filter_narrows_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("g", "i", "t", "h", "u", "b")
        await page.wait_for(
            lambda _s: (
                [e.name for _, _, e_list in pane._grouped for e in e_list] == ["github"]
            )
        )
        labels = _option_labels(pane)
        assert any("github" in label for label in labels)
        assert not any("telegram" in label for label in labels)
        # Cancelling restores the full list.
        pane.cancel_input()
        await page.wait_for(
            lambda _s: any(
                e.name == "telegram" for _, _, lst in pane._grouped for e in lst
            )
        )


async def test_plugins_pane_filter_no_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("z", "z", "z", "z")
        await page.wait_for(lambda _s: not pane._grouped)
        assert pane.query_one("#plugins-status").display is True
        assert "No plugins match" in pane._status_message()


async def test_plugins_pane_empty_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    empty = PluginCatalog(fetched_at=_NOW, entries=(), from_cache=True, stale=False)
    _patch_catalog(monkeypatch, catalog=empty)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane.query_one("#plugins-status").display is True
        assert pane.query_one("#plugins-list").display is False
        assert "No SASE plugins found." in pane._status_message()


async def test_plugins_pane_error_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=None, error="gh not found")
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane._error == "gh not found"
        assert pane.query_one("#plugins-status").display is True
        assert "gh not found" in pane._status_message()


async def test_config_center_cycles_six_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        assert modal._active_tab == "config"
        # Tasks sits directly right of Config; Logs and Projects follow it.
        modal.action_next_center_tab()
        assert modal._active_tab == "tasks"
        modal.action_next_center_tab()
        assert modal._active_tab == "logs"
        modal.action_next_center_tab()
        assert modal._active_tab == "projects"
        modal.action_next_center_tab()
        assert modal._active_tab == "plugins"
        modal.action_next_center_tab()
        assert modal._active_tab == "xprompts"
        modal.action_next_center_tab()
        assert modal._active_tab == "config"
        # Wrapping backwards lands on the rightmost XPrompts tab.
        modal.action_prev_center_tab()
        assert modal._active_tab == "xprompts"

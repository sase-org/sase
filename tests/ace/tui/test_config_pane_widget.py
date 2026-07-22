"""Loading, filtering, and edit-launch tests for the Config pane widget."""

from __future__ import annotations

import pytest
from textual.widgets import Input

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal
from tests.ace.tui._config_pane_widget_helpers import (
    _open_config_pane,
    _patch_loaders,
)


async def test_config_pane_loads_and_populates_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        # Sections and leaves are present.
        assert "axe" in pane._node_by_path
        assert "axe.max_hook_runners" in pane._node_by_path
        assert "timezone" in pane._node_by_path
        # A leaf is auto-selected so the detail pane has something to show.
        assert pane._selected_path is not None
        assert pane._view is not None
        # The status placeholder is hidden and the tree is visible.
        assert pane.query_one("#config-tree").display is True
        assert pane.query_one("#config-field-status").display is False


async def test_config_pane_filter_narrows_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("t", "i", "m", "e", "z", "o", "n", "e")
        await page.wait_for(lambda _s: set(pane._node_by_path) == {"timezone"})
        assert "axe.max_hook_runners" not in pane._node_by_path
        # Cancelling restores the full tree.
        pane.cancel_input()
        await page.wait_for(lambda _s: "axe.max_hook_runners" in pane._node_by_path)


async def test_config_pane_filter_updates_title_match_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("t", "i", "m", "e", "z", "o", "n", "e")
        await page.wait_for(lambda _s: set(pane._node_by_path) == {"timezone"})
        assert "matching 1 /" in pane._title_text()


async def test_config_filter_accepts_brackets_and_tab_switches_main_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        pane.action_focus_filter()
        filter_input = pane.query_one("#config-filter-input", Input)
        await page.wait_for(lambda _s: filter_input.has_focus)

        await page.press("left_square_bracket", "right_square_bracket")
        await page.wait_for(lambda _s: filter_input.value == "[]")
        assert modal._active_tab == "config"

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "logs")
        assert filter_input.value == "[]"
        assert page.app.current_tab == "changespecs"


async def test_config_pane_modified_only_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _patch_loaders(monkeypatch)
    modified = view.modified_paths()
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_toggle_modified()
        await page.pause()
        shown_leaves = {
            path for path in pane._node_by_path if view.fields_by_path[path].leaf
        }
        assert shown_leaves == modified
        assert "use_chezmoi" not in shown_leaves  # only built-in default
        # Toggling back restores every leaf.
        pane.action_toggle_modified()
        await page.pause()
        assert "use_chezmoi" in pane._node_by_path


async def test_config_pane_jump_selects_matching_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("chop")
        await page.wait_for(lambda _s: pane._selected_path == "axe.chop_script_dirs")
        assert "axe.chop_script_dirs" in pane._node_by_path


async def test_config_pane_edit_opens_edit_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("timezone")
        await page.wait_for(lambda _s: pane._selected_path == "timezone")
        pane.action_edit_field()
        await page.expect_modal("ConfigEditModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigEditModal)
        assert modal._field is not None and modal._field.path == "timezone"


async def test_config_pane_edit_sibling_repos_opens_normal_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("sibling_repos")
        await page.wait_for(lambda _s: pane._selected_path == "sibling_repos")
        pane.action_edit_field()
        await page.expect_modal("ConfigEditModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigEditModal)
        assert modal._field is not None and modal._field.path == "sibling_repos"

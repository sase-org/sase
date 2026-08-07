"""Apostrophe entry-jump tests for the Config Center Config pane."""

from __future__ import annotations

import pytest
from textual.widgets import Input, Static, Tree

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_pane import ConfigPane
from tests.ace.tui._config_pane_widget_helpers import (
    _open_config_pane,
    _patch_loaders,
)


def _visible_paths(pane: ConfigPane) -> list[str]:
    return [node.data for node in pane._jump_nodes() if isinstance(node.data, str)]


def _label_text(pane: ConfigPane, path: str) -> str:
    return pane._node_by_path[path].label.plain


async def _focus_tree(page: AcePage, pane: ConfigPane) -> Tree[str]:
    tree = pane.query_one("#config-tree", Tree)
    tree.focus()
    await page.pause()
    return tree


async def test_config_jump_paints_hints_over_visible_rows_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        await _focus_tree(page, pane)
        paths = _visible_paths(pane)
        assert len(paths) > 3

        await page.press("apostrophe")
        await page.wait_for(lambda _s: pane.jump_mode_active)

        for index, path in enumerate(paths):
            hint = pane.jump_hint_for(index)
            assert hint is not None
            assert _label_text(pane, path).startswith(f"[{hint}] ")
        assert pane.jump_hint_for(0) == "0"
        assert pane.jump_hint_for(1) == "1"


async def test_config_jump_hint_moves_cursor_and_repaints_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        tree = await _focus_tree(page, pane)
        paths = _visible_paths(pane)
        target = paths[2]

        await page.press("apostrophe")
        await page.wait_for(lambda _s: pane.jump_mode_active)
        await page.press("2")
        await page.wait_for(lambda _s: pane._selected_path == target)

        assert not pane.jump_mode_active
        assert tree.cursor_node is not None
        assert tree.cursor_node.data == target
        detail = str(pane.query_one("#config-detail-body", Static).content)
        assert target.rsplit(".", 1)[-1] in detail
        # Hints are gone once the jump lands.
        assert _label_text(pane, target).startswith("[") is False


async def test_config_jump_second_apostrophe_returns_to_prior_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        await _focus_tree(page, pane)
        paths = _visible_paths(pane)
        origin = pane._selected_path
        assert origin is not None

        await page.press("apostrophe")
        await page.wait_for(lambda _s: pane.jump_mode_active)
        await page.press("3")
        await page.wait_for(lambda _s: pane._selected_path == paths[3])
        assert pane.jump_back_stack

        await page.press("apostrophe")
        await page.wait_for(lambda _s: pane.jump_mode_active)
        await page.press("apostrophe")
        await page.wait_for(lambda _s: pane._selected_path == origin)

        assert not pane.jump_mode_active
        assert not pane.jump_back_stack


async def test_config_jump_escape_cancels_without_moving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        await _focus_tree(page, pane)
        selected_before = pane._selected_path
        labels_before = {path: _label_text(pane, path) for path in pane._node_by_path}

        await page.press("apostrophe")
        await page.wait_for(lambda _s: pane.jump_mode_active)
        await page.press("escape")
        await page.wait_for(lambda _s: not pane.jump_mode_active)

        assert pane._selected_path == selected_before
        assert {
            path: _label_text(pane, path) for path in pane._node_by_path
        } == labels_before


async def test_config_jump_preserves_collapsed_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        await _focus_tree(page, pane)
        pane._do_jump("axe.max_hook_runners")
        await page.wait_for(lambda _s: pane._selected_path == "axe.max_hook_runners")
        pane.action_collapse_tree()
        await page.wait_for(lambda _s: pane._selected_path == "axe")
        pane.action_collapse_tree()
        await page.pause()
        axe_node = pane._node_by_path["axe"]
        assert axe_node.is_collapsed
        # Collapsed children are not jump targets.
        assert "axe.max_hook_runners" not in _visible_paths(pane)

        await page.press("apostrophe")
        await page.wait_for(lambda _s: pane.jump_mode_active)
        assert axe_node.is_collapsed
        await page.press("escape")
        await page.wait_for(lambda _s: not pane.jump_mode_active)

        assert axe_node.is_collapsed
        assert pane._selected_path == "axe"


async def test_config_jump_hints_cleared_when_filter_rebuilds_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        await _focus_tree(page, pane)

        await page.press("apostrophe")
        await page.wait_for(lambda _s: pane.jump_mode_active)

        # A filter change is the one row rebuild that can land while hints are
        # painted, since every hint-alphabet key is consumed by jump mode.
        pane.query_one("#config-filter-input", Input).value = "timezone"
        await page.wait_for(lambda _s: set(pane._node_by_path) == {"timezone"})

        assert not pane.jump_mode_active
        assert pane.jump_hint_for(0) is None
        assert not _label_text(pane, "timezone").startswith("[")


async def test_config_jump_is_noop_while_filter_input_has_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_focus_filter()
        await page.pause()

        await page.press("apostrophe")
        await page.pause()

        assert not pane.jump_mode_active
        assert pane.query_one("#config-filter-input", Input).value == "'"


async def test_config_jump_hint_line_switches_to_jump_variant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        await _focus_tree(page, pane)
        assert "': hint" in pane._hints()
        assert ":: path" in pane._hints()
        assert len(pane._hints()) <= 120

        await page.press("apostrophe")
        await page.wait_for(lambda _s: pane.jump_mode_active)

        assert pane._hints() == "JUMP ' first  <esc> cancel"

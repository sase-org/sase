"""Keyboard navigation and detail scrolling tests for the Config pane widget."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Tree

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals.config_pane import ConfigPane
from sase.config.inventory import build_config_inventory, config_field_model
from tests.ace.tui._config_pane_widget_helpers import (
    _open_config_pane,
    _patch_loaders,
)
from tests.test_config_pane import _fixture_layers, _fixture_schema


def _tall_detail_view() -> cp.ConfigPaneView:
    schema: dict[str, Any] = _fixture_schema()
    schema["properties"]["long_detail"] = {
        "type": "string",
        "default": "builtin",
        "description": "\n".join(
            f"Long detail line {index:02d} for config detail scrolling."
            for index in range(48)
        ),
    }
    layers = _fixture_layers()
    layers[0].data["long_detail"] = "builtin"
    layers[1].data["long_detail"] = "user"
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=layers,
    ):
        inventory = build_config_inventory(schema=schema)
    field_model = config_field_model(schema)
    return cp.ConfigPaneView.build(field_model, inventory)


def _binding_action(key: str) -> str | None:
    """Action bound to *key* in ``ConfigPane.BINDINGS`` (tuple or Binding)."""
    for binding in ConfigPane.BINDINGS:
        if isinstance(binding, tuple):
            bind_key, action = binding[0], binding[1]
        else:
            bind_key, action = binding.key, binding.action
        if bind_key == key:
            return action
    return None


async def test_config_detail_ctrl_d_u_scrolls_without_stealing_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch, _tall_detail_view())
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("long_detail")
        await page.wait_for(lambda _s: pane._selected_path == "long_detail")
        tree = pane.query_one("#config-tree", Tree)
        tree.focus()
        await page.pause()

        scroll = pane.query_one("#config-detail-scroll", VerticalScroll)
        await page.wait_for(lambda _s: scroll.max_scroll_y > 0)
        selected_before = pane._selected_path
        assert page.app.focused is tree
        assert scroll.scroll_y == 0

        await page.press("ctrl+d")
        await page.pause()
        down_y = scroll.scroll_y
        assert down_y > 0
        assert page.app.focused is tree
        assert pane._selected_path == selected_before

        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0
        assert page.app.focused is tree
        assert pane._selected_path == selected_before


async def test_config_detail_ctrl_d_u_on_short_detail_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("use_chezmoi")
        await page.wait_for(lambda _s: pane._selected_path == "use_chezmoi")
        tree = pane.query_one("#config-tree", Tree)
        tree.focus()
        await page.pause()

        scroll = pane.query_one("#config-detail-scroll", VerticalScroll)
        assert scroll.max_scroll_y == 0
        await page.press("ctrl+d")
        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0
        assert page.app.focused is tree


def test_config_pane_binds_ctrl_d_and_ctrl_u_to_detail_scroll() -> None:
    assert _binding_action("ctrl+d") == "scroll_detail_down"
    assert _binding_action("ctrl+u") == "scroll_detail_up"
    assert _binding_action("g") == "scroll_to_top"
    assert _binding_action("G") == "scroll_to_bottom"
    assert _binding_action("h") == "collapse_tree"
    assert _binding_action("l") == "expand_tree"
    assert "^d/u,g/G: scroll" in ConfigPane(auto_load=False)._hints()
    assert "g: migrate" not in ConfigPane(auto_load=False)._hints()


def test_config_pane_splits_cycling_j_k_from_clamped_arrow_keys() -> None:
    assert _binding_action("j") == "cycle_cursor_down"
    assert _binding_action("k") == "cycle_cursor_up"
    assert _binding_action("down") == "cursor_down"
    assert _binding_action("up") == "cursor_up"


async def test_config_pane_j_k_wrap_visible_tree_and_arrows_clamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        tree = pane.query_one("#config-tree", Tree)
        tree.focus()

        pane.action_scroll_to_bottom()
        await page.wait_for(lambda _s: tree.cursor_line == tree.last_line)
        last_path = pane._selected_path
        await page.press("j")
        await page.wait_for(lambda _s: tree.cursor_line == 0)
        first_path = pane._selected_path
        assert tree.cursor_node is not None
        assert tree.cursor_node.data == first_path

        await page.press("k")
        await page.wait_for(lambda _s: tree.cursor_line == tree.last_line)
        assert pane._selected_path == last_path
        assert tree.cursor_node is not None
        assert tree.cursor_node.data == last_path

        await page.press("down")
        await page.pause()
        assert tree.cursor_line == tree.last_line
        assert pane._selected_path == last_path

        pane.action_scroll_to_top()
        await page.wait_for(lambda _s: tree.cursor_line == 0)
        assert pane._selected_path == first_path
        await page.press("up")
        await page.pause()
        assert tree.cursor_line == 0
        assert pane._selected_path == first_path


async def test_config_pane_j_k_cycle_single_visible_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("t", "i", "m", "e", "z", "o", "n", "e")
        await page.wait_for(lambda _s: set(pane._node_by_path) == {"timezone"})
        pane.focus_default()
        tree = pane.query_one("#config-tree", Tree)
        await page.wait_for(lambda _s: tree.cursor_line == tree.last_line == 0)

        await page.press("j", "k")
        await page.pause()

        assert tree.cursor_line == 0
        assert tree.cursor_node is not None
        assert tree.cursor_node.data == "timezone"
        assert pane._selected_path == "timezone"


async def test_config_pane_g_and_G_jump_tree_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_scroll_to_bottom()
        await page.wait_for(lambda _s: pane._selected_path == "use_chezmoi")
        pane.action_scroll_to_top()
        await page.wait_for(lambda _s: pane._selected_path == "ace")


async def test_config_pane_h_l_collapse_expand_and_descend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("axe.max_hook_runners")
        await page.wait_for(lambda _s: pane._selected_path == "axe.max_hook_runners")

        pane.action_collapse_tree()
        await page.wait_for(lambda _s: pane._selected_path == "axe")
        axe_node = pane._node_by_path["axe"]
        pane.action_collapse_tree()
        await page.pause()
        assert axe_node.is_collapsed

        pane.action_expand_tree()
        await page.pause()
        assert axe_node.is_expanded
        assert pane._selected_path == "axe"

        pane.action_expand_tree()
        await page.wait_for(lambda _s: pane._selected_path == "axe.chop_script_dirs")


async def test_config_pane_ctrl_d_and_ctrl_u_scroll_detail_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage(size=(120, 30)) as page:
        pane = await _open_config_pane(page)
        pane._do_jump("ace.lumberjack")
        await page.wait_for(lambda _s: pane._selected_path == "ace.lumberjack")

        tree = pane.query_one("#config-tree", Tree)
        cursor_before = tree.cursor_node.data if tree.cursor_node is not None else None
        selected_before = pane._selected_path
        scroll = pane.query_one("#config-detail-scroll", VerticalScroll)
        await page.wait_for(lambda _s: scroll.max_scroll_y > 0)
        assert scroll.scroll_y == 0

        half_page = scroll.scrollable_content_region.height // 2
        assert half_page > 0

        await page.press("ctrl+d")
        await page.pause()
        expected_down = min(half_page, scroll.max_scroll_y)
        assert scroll.scroll_y == expected_down
        assert pane._selected_path == selected_before
        assert tree.cursor_node is not None and tree.cursor_node.data == cursor_before

        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0
        assert pane._selected_path == selected_before
        assert tree.cursor_node is not None and tree.cursor_node.data == cursor_before

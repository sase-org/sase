"""Widget-level tests for the Config Center Config tab (Phase 4).

These cover the parts the pure helpers cannot: the worker-backed inventory load
populating the tree, the loading→populated transition, the live filter input,
the modified-only toggle, and jump-to-path. The config backend is patched with a
deterministic fixture view so no real config files are read.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_pane import ConfigPane
from sase.config.inventory import build_config_inventory, config_field_model
from tests.test_config_pane import _fixture_layers, _fixture_schema


def _fixture_view() -> cp.ConfigPaneView:
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=_fixture_layers(),
    ):
        inventory = build_config_inventory(schema=_fixture_schema())
    field_model = config_field_model(_fixture_schema())
    return cp.ConfigPaneView.build(field_model, inventory)


def _patch_loaders(monkeypatch: pytest.MonkeyPatch) -> cp.ConfigPaneView:
    view = _fixture_view()
    result = cp._LoadResult(view=view, error=None, token=("tok", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: result)
    # Keep the XPrompts pane cheap and deterministic.
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    return view


async def _open_config_pane(page: AcePage) -> ConfigPane:
    modal = ConfigCenterModal(initial_tab="config")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#config")))
    pane = modal.query_one("#config", ConfigPane)
    await page.wait_for(lambda _s: bool(pane._node_by_path))
    return pane


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
    from sase.ace.tui.modals.config_edit_modal import ConfigEditModal

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


async def test_config_pane_migrate_opens_migration_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.modals.config_edit_modal import ConfigEditModal

    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        # The fixture user layer sets sibling_repos, so migration is available.
        pane.action_migrate()
        await page.expect_modal("ConfigEditModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigEditModal)
        assert modal._mode == "migration"

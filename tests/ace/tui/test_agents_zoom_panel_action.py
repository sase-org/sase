"""Tests for the Agents-tab zoom panel action and related key routing."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.app import AceApp
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal

from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _patch_catalog,
    _patch_other_panes,
)


def test_default_zoom_migrates_to_uppercase_z_and_fold_keeps_lowercase() -> None:
    registry = load_keymap_registry({})
    bindings = build_app_bindings(registry.app)

    assert registry.app.start_fold_mode == "z"
    assert registry.app.zoom_panel == "Z"
    assert registry.app.isolate_panels == "="
    assert [binding.action for binding in bindings if binding.key == "z"] == [
        "start_fold_mode",
        "stitches_cycle_merges",
        "beads_snooze",
        "files_cycle_kind",
    ]
    assert [binding.action for binding in bindings if binding.key == "Z"] == [
        "zoom_panel",
        "files_open_viewer",
    ]
    assert [binding.action for binding in bindings if binding.key == "="] == [
        "isolate_panels",
    ]


def test_zoom_and_fold_actions_are_tab_gated() -> None:
    agents_app = AceApp(auto_start_axe=False, initial_tab="agents")
    patches_app = AceApp(auto_start_axe=False, initial_tab="patches")
    axe_app = AceApp(auto_start_axe=False, initial_tab="axe")

    assert agents_app.check_action("start_fold_mode", ()) is not False
    assert agents_app.check_action("zoom_panel", ()) is not False
    assert patches_app.check_action("zoom_panel", ()) is False
    patches_app.current_artifacts_subtab = "patches"
    assert patches_app.check_action("start_fold_mode", ()) is not False
    assert axe_app.check_action("start_fold_mode", ()) is False

    patches_app.current_artifacts_subtab = "stitches"
    assert patches_app.check_action("start_fold_mode", ()) is False


def test_all_panel_fold_sweep_is_agents_only_underscore_reaches_next_query() -> None:
    """``underscore`` resolves to distinct actions per tab, never a real conflict."""
    agents_app = AceApp(auto_start_axe=False, initial_tab="agents")
    patches_app = AceApp(auto_start_axe=False, initial_tab="patches")
    patches_app.current_artifacts_subtab = "patches"

    assert agents_app.check_action("collapse_all_panel_folds", ()) is not False
    assert patches_app.check_action("collapse_all_panel_folds", ()) is False

    assert agents_app.check_action("next_query", ()) is False
    assert patches_app.check_action("next_query", ()) is not False


def test_metadata_sections_are_unavailable_now_that_decks_are_unconditional() -> None:
    agents_app = AceApp(auto_start_axe=False, initial_tab="agents")
    patches_app = AceApp(auto_start_axe=False, initial_tab="patches")
    axe_app = AceApp(auto_start_axe=False, initial_tab="axe")
    patches_app.current_artifacts_subtab = "patches"

    for action in (
        "next_agent_metadata_section",
        "prev_agent_metadata_section",
    ):
        assert agents_app.check_action(action, ()) is False
        assert patches_app.check_action(action, ()) is False
        assert axe_app.check_action(action, ()) is False

    for app in (agents_app, patches_app, axe_app):
        assert app.check_action("jump_to_entry_forward", ()) is not False


async def test_ctrl_shift_o_dispatches_forward_jump_on_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def record_forward_jump(app: AceApp) -> None:
        calls.append(app.current_tab)

    monkeypatch.setattr(AceApp, "action_jump_to_entry_forward", record_forward_jump)

    async with AcePage(initial_tab="agents") as page:
        await page.press("ctrl+shift+o")
        await page.pause()

    assert calls == ["agents"]


async def test_clear_marks_action_is_disabled_while_modal_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        page.app.push_screen(ConfigCenterModal(initial_tab="updates"))
        await page.expect_modal("ConfigCenterModal")

        assert page.app.check_action("clear_marks", ()) is False


def test_fold_and_bead_snooze_never_contend_for_lowercase_z() -> None:
    """``z`` is shared, so exactly one of its actions may be live at a time."""
    app = AceApp(auto_start_axe=False, initial_tab="patches")

    app.current_artifacts_subtab = "beads"
    assert app.check_action("start_fold_mode", ()) is False
    assert app.check_action("beads_snooze", ()) is not False

    app.current_artifacts_subtab = "patches"
    assert app.check_action("start_fold_mode", ()) is not False
    assert app.check_action("beads_snooze", ()) is False

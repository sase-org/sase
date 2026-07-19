"""Tests for the Agents-tab zoom panel action and related key routing."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.app import AceApp
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals import ZoomPanelModal, ZoomPanelTarget
from sase.ace.tui.widgets.tools_panel import ToolDetailLevel

from tests.ace.tui._agents_zoom_panel_helpers import (
    _FakeDetail,
    _FakeZoomApp,
    _make_agent,
)
from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _patch_catalog,
    _patch_other_panes,
)


@pytest.mark.parametrize(
    ("detail", "attempt", "expected"),
    [
        (_FakeDetail(file_visible=True), None, ZoomPanelTarget.FILE),
        (
            _FakeDetail(tools_visible=True, file_visible=False, has_tools=True),
            None,
            ZoomPanelTarget.TOOLS,
        ),
        (
            _FakeDetail(layout_swapped=True, tools_visible=True, has_tools=True),
            None,
            ZoomPanelTarget.METADATA,
        ),
        (_FakeDetail(info=True, file_visible=False), None, ZoomPanelTarget.METADATA),
        (_FakeDetail(file_visible=True), 2, ZoomPanelTarget.METADATA),
    ],
)
def test_action_zoom_panel_selects_expected_initial_target(
    detail: _FakeDetail,
    attempt: int | None,
    expected: ZoomPanelTarget,
) -> None:
    app = _FakeZoomApp(
        agent=_make_agent(),
        detail=detail,
        current_attempt_number=attempt,
    )

    app.action_zoom_panel()

    assert len(app.pushed) == 1
    modal = app.pushed[0]
    assert isinstance(modal, ZoomPanelModal)
    assert modal._target == expected
    assert modal._seed.attempt_view_mode == "current-only"


def test_action_zoom_panel_warns_without_agent() -> None:
    app = _FakeZoomApp(agent=None)

    app.action_zoom_panel()

    assert app.pushed == []
    assert app.notifications == [("No agent selected", "warning")]


def test_action_zoom_panel_provider_resolves_fresh_agent_by_identity() -> None:
    agent = _make_agent(status="RUNNING")
    app = _FakeZoomApp(agent=agent)

    app.action_zoom_panel()
    modal = app.pushed[0]
    refreshed = _make_agent(status="DONE")
    app._agents = [refreshed]
    app._agents_with_children = [refreshed]

    assert modal._agent_provider() is refreshed


def test_action_zoom_panel_seed_carries_tools_detail_level() -> None:
    detail = _FakeDetail(tools_visible=True, file_visible=False, has_tools=True)
    detail.tools_detail_level = ToolDetailLevel.FULL  # type: ignore[attr-defined]
    app = _FakeZoomApp(agent=_make_agent(), detail=detail)

    app.action_zoom_panel()

    modal = app.pushed[0]
    assert modal._seed.tools_detail_level == ToolDetailLevel.FULL


def test_default_zoom_migrates_to_uppercase_z_and_fold_keeps_lowercase() -> None:
    registry = load_keymap_registry({})
    bindings = build_app_bindings(registry.app)

    assert registry.app.start_fold_mode == "z"
    assert registry.app.zoom_panel == "Z"
    assert [binding.action for binding in bindings if binding.key == "z"] == [
        "start_fold_mode"
    ]
    assert [binding.action for binding in bindings if binding.key == "Z"] == [
        "zoom_panel"
    ]


def test_zoom_and_fold_actions_are_tab_gated() -> None:
    agents_app = AceApp(auto_start_axe=False, initial_tab="agents")
    changespecs_app = AceApp(auto_start_axe=False, initial_tab="changespecs")
    axe_app = AceApp(auto_start_axe=False, initial_tab="axe")

    assert agents_app.check_action("start_fold_mode", ()) is not False
    assert agents_app.check_action("zoom_panel", ()) is not False
    assert changespecs_app.check_action("zoom_panel", ()) is False
    assert changespecs_app.check_action("start_fold_mode", ()) is not False
    assert axe_app.check_action("start_fold_mode", ()) is False

    changespecs_app.current_artifacts_subtab = "commits"
    assert changespecs_app.check_action("start_fold_mode", ()) is False


def test_metadata_sections_and_forward_jump_are_inverse_tab_gated() -> None:
    agents_app = AceApp(auto_start_axe=False, initial_tab="agents")
    changespecs_app = AceApp(auto_start_axe=False, initial_tab="changespecs")
    axe_app = AceApp(auto_start_axe=False, initial_tab="axe")

    for action in (
        "next_agent_metadata_section",
        "prev_agent_metadata_section",
    ):
        assert agents_app.check_action(action, ()) is not False
        assert changespecs_app.check_action(action, ()) is False
        assert axe_app.check_action(action, ()) is False

    assert agents_app.check_action("jump_to_entry_forward", ()) is False
    assert changespecs_app.check_action("jump_to_entry_forward", ()) is not False
    assert axe_app.check_action("jump_to_entry_forward", ()) is not False


async def test_clear_marks_action_is_disabled_while_modal_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        page.app.push_screen(ConfigCenterModal(initial_tab="updates"))
        await page.expect_modal("ConfigCenterModal")

        assert page.app.check_action("clear_marks", ()) is False

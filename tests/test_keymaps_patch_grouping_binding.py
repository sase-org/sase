"""Regression coverage for grouping-cycle vs Artifacts open-externally keys.

``o`` / ``O`` cycle the grouping strategy on every surface that has a grouping
mode. The two Artifacts open-externally actions (``beads_open_bug``,
``files_open_external``) share ``E``. Bang-mode ``!o`` still owns
``mark_pr_origin``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.artifact_tabs import artifacts_pane_contract
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.tab_order import ARTIFACTS_TAB


def test_unbound_app_command_has_no_key_display() -> None:
    from sase.ace.tui.commands.catalog import build_command_catalog

    catalog = {
        spec.id: spec for spec in build_command_catalog(load_keymap_registry({}))
    }
    assert catalog["app.mark_pr_origin"].key_sequence == ("unbound",)
    assert catalog["app.mark_pr_origin"].key_display == ""
    assert catalog["bang.mark_pr_origin"].key_display == "!o"


def test_mark_pr_origin_defaults_to_bang_mode() -> None:
    reg = load_keymap_registry({})
    assert reg.app.mark_pr_origin == "unbound"
    assert reg.app.cycle_grouping_mode == "o"
    assert reg.app.cycle_grouping_mode_reverse == "O"
    assert reg.app.beads_open_bug == "E"
    assert reg.app.files_open_external == "E"
    assert reg.bang_mode.keys["mark_pr_origin"] == "o"

    o_actions = [
        binding.action for binding in build_app_bindings(reg.app) if binding.key == "o"
    ]
    assert "mark_pr_origin" not in o_actions
    assert "cycle_grouping_mode" in o_actions

    e_actions = [
        binding.action for binding in build_app_bindings(reg.app) if binding.key == "E"
    ]
    assert "beads_open_bug" in e_actions
    assert "files_open_external" in e_actions


def test_patch_pane_o_reaches_grouping_not_mark_pr_origin() -> None:
    """On Patches, ``o`` / ``O`` cycle grouping; ``mark_pr_origin`` stays bang-mode."""

    o_actions = [
        binding.action
        for binding in build_app_bindings(load_keymap_registry({}).app)
        if binding.key == "o"
        and _action_enabled(binding.action, tab=ARTIFACTS_TAB, pane="patches")
    ]
    assert o_actions == ["cycle_grouping_mode"]

    o_rev_actions = [
        binding.action
        for binding in build_app_bindings(load_keymap_registry({}).app)
        if binding.key == "O"
        and _action_enabled(binding.action, tab=ARTIFACTS_TAB, pane="patches")
    ]
    assert o_rev_actions == ["cycle_grouping_mode_reverse"]


@pytest.mark.parametrize(
    ("pane", "key", "expected"),
    [
        ("stitches", "o", ["cycle_grouping_mode"]),
        ("stitches", "O", ["cycle_grouping_mode_reverse"]),
        ("stitches", "E", []),
        ("patches", "o", ["cycle_grouping_mode"]),
        ("patches", "O", ["cycle_grouping_mode_reverse"]),
        ("patches", "E", ["edit_panel"]),
        ("files", "o", ["cycle_grouping_mode"]),
        ("files", "O", ["cycle_grouping_mode_reverse"]),
        ("files", "E", ["files_open_external"]),
        ("beads", "o", []),
        ("beads", "O", []),
        ("beads", "E", ["beads_open_bug"]),
        ("ref:plan", "o", []),
        ("ref:plan", "O", []),
        ("ref:plan", "E", []),
    ],
)
def test_pane_key_resolution(pane: str, key: str, expected: list[str]) -> None:
    actions = [
        binding.action
        for binding in build_app_bindings(load_keymap_registry({}).app)
        if binding.key == key
        and _action_enabled(binding.action, tab=ARTIFACTS_TAB, pane=pane)
    ]
    assert actions == expected


def _action_enabled(action: str, *, tab: str, pane: str | None) -> bool:
    app = SimpleNamespace(
        current_tab=tab,
        current_artifacts_pane_key=pane,
        current_artifacts_subtab=pane,
        active_artifacts_contract=artifacts_pane_contract(pane) if pane else None,
        screen=object(),
        focused=None,
        _screen_stack=(),
        _prompt_input_active=lambda: False,
        _active_documents_pane=lambda: None,
        _agent_metadata_search=None,
    )
    try:
        result = check_app_action(app, action, (), lambda _action, _params: True)
    except Exception:
        return False
    return result is not False

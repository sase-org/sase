"""Regression coverage for the Patch pane `o` grouping / PR-origin collision."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui._app_action_availability import check_app_action
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
    assert reg.bang_mode.keys["mark_pr_origin"] == "o"

    o_actions = [
        binding.action for binding in build_app_bindings(reg.app) if binding.key == "o"
    ]
    assert "mark_pr_origin" not in o_actions
    assert "cycle_grouping_mode" in o_actions


def test_patch_pane_o_reaches_grouping_and_not_mark_pr_origin() -> None:
    """sase-m5: `o` on Patches must cycle grouping, not open PR origin."""

    o_actions = [
        binding.action
        for binding in build_app_bindings(load_keymap_registry({}).app)
        if binding.key == "o"
        and _action_enabled(binding.action, tab=ARTIFACTS_TAB, pane="patches")
    ]
    assert o_actions[0] == "cycle_grouping_mode"
    assert "mark_pr_origin" not in o_actions


def _action_enabled(action: str, *, tab: str, pane: str | None) -> bool:
    app = SimpleNamespace(
        current_tab=tab,
        current_artifacts_pane_key=pane,
        current_artifacts_subtab=pane,
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

"""Regression coverage for the Patch pane `o` grouping / PR-origin collision.

sase-m6.9 fully resolved the underlying collision: `o`/`O` are now reserved
app-wide for the unified "open" verb (`beads_open_bug`, `files_open_external`)
and never reach grouping on any pane, including Patches. Grouping-cycle moved
to its own dedicated key (`B` / reverse `I`) so it no longer needs a per-pane
exception list at all.
"""

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
    assert reg.app.cycle_grouping_mode == "B"
    assert reg.bang_mode.keys["mark_pr_origin"] == "o"

    o_actions = [
        binding.action for binding in build_app_bindings(reg.app) if binding.key == "o"
    ]
    assert "mark_pr_origin" not in o_actions
    assert "cycle_grouping_mode" not in o_actions

    b_actions = [
        binding.action for binding in build_app_bindings(reg.app) if binding.key == "B"
    ]
    assert "cycle_grouping_mode" in b_actions


def test_patch_pane_o_reaches_neither_grouping_nor_mark_pr_origin() -> None:
    """sase-m6.9: `o` on Patches is unbound; grouping moved to `B` everywhere."""

    o_actions = [
        binding.action
        for binding in build_app_bindings(load_keymap_registry({}).app)
        if binding.key == "o"
        and _action_enabled(binding.action, tab=ARTIFACTS_TAB, pane="patches")
    ]
    assert o_actions == []

    b_actions = [
        binding.action
        for binding in build_app_bindings(load_keymap_registry({}).app)
        if binding.key == "B"
        and _action_enabled(binding.action, tab=ARTIFACTS_TAB, pane="patches")
    ]
    assert b_actions == ["cycle_grouping_mode"]


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

"""Tests for the leader ``,A`` Agent Run Log fallback keymap."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.modals.agent_run_log_modal import AgentRunLogModal

from tests.ace.tui._leader_keymap_helpers import (
    _FakeApp,
    _FakeEntryPoints,
    _make_cs,
)


def test_default_keymap_binds_v_to_agent_run_log_and_a_to_artifacts() -> None:
    registry = load_keymap_registry({})

    assert registry.app.show_agent_run_log == "V"
    assert registry.app.view_agent_metadata == "V"
    assert registry.app.open_artifact_files == "a"
    assert registry.app.accept_proposal == "A"
    assert registry.app.start_agent_home == "space"
    assert registry.app.start_agent_from_patch == "ctrl+@"
    assert registry.leader_mode.keys["agent_run_log"] == "A"
    assert registry.leader_mode.keys["agent_home"] == "h"
    assert registry.leader_mode.keys["agent_from_cl"] == "space"
    assert registry.app.focus_next_agent_panel == "J"
    assert registry.leader_mode.keys["jump_to_next_stopped_agent"] == "J"
    assert registry.leader_mode.keys["full_history_refresh"] == "y"
    assert registry.leader_mode.keys["mark_all_unread_done_agents_read"] == "u"

    bindings = build_app_bindings(registry.app)
    by_key = {b.key: b.action for b in bindings if b.key != "V"}
    assert by_key["a"] == "open_artifact_files"
    assert by_key["A"] == "accept_proposal"
    assert by_key["J"] == "focus_next_agent_panel"
    assert by_key["space"] == "start_agent_home"
    assert by_key["ctrl+@"] == "start_agent_from_patch"

    # `V` is tab-disjoint: both actions bind to the key, and
    # `check_app_action` (not the bindings list) picks the one that applies
    # to the current tab.
    v_actions = {b.action for b in bindings if b.key == "V"}
    assert v_actions == {"show_agent_run_log", "view_agent_metadata"}


def test_action_start_agent_home_opens_home_prompt() -> None:
    app = _FakeEntryPoints()

    app.action_start_agent_home()

    assert app.home_agent_count == 1


def test_leader_a_opens_agent_run_log_for_selected_cl() -> None:
    app = _FakeApp(patches=[_make_cs("alpha"), _make_cs("beta")])
    app.current_idx = 1

    with patch(
        "sase.ace.tui.modals.agent_run_log_modal._load_agents_for_cl",
        return_value=([], set()),
    ):
        handled = app._handle_leader_key("A")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.refresh_count == 1
    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentRunLogModal)
    assert modal._cl_name == "beta"


def test_leader_a_noops_on_non_cls_tabs() -> None:
    app = _FakeApp(patches=[_make_cs("alpha")], current_tab="agents")

    handled = app._handle_leader_key("A")

    assert handled is True
    assert app.refresh_count == 1
    assert app.pushed_modals == []


def test_leader_a_noops_with_empty_cls_list() -> None:
    app = _FakeApp(patches=[])

    handled = app._handle_leader_key("A")

    assert handled is True
    assert app.refresh_count == 1
    assert app.pushed_modals == []


def test_v_still_opens_agent_run_log_modal_on_the_patches_tab() -> None:
    """Regression for the tab-disjoint split: Patches keeps `V` on the modal."""
    app = _FakeApp(patches=[_make_cs("alpha")], current_tab="patches")

    with patch(
        "sase.ace.tui.modals.agent_run_log_modal._load_agents_for_cl",
        return_value=([], set()),
    ):
        app.action_show_agent_run_log()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentRunLogModal)
    assert modal._cl_name == "alpha"


def test_v_action_body_noops_on_the_agents_tab() -> None:
    """`action_show_agent_run_log` still self-guards; the real gate is
    `check_app_action`, but the action body must stay a safe no-op too."""
    app = _FakeApp(patches=[_make_cs("alpha")], current_tab="agents")

    app.action_show_agent_run_log()

    assert app.pushed_modals == []

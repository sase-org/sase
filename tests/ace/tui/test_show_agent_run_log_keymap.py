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
    assert registry.app.open_artifact_files == "a"
    assert registry.app.accept_proposal == "A"
    assert registry.app.start_agent_home == "space"
    assert registry.app.start_agent_from_changespec == "ctrl+@"
    assert registry.leader_mode.keys["agent_run_log"] == "A"
    assert registry.leader_mode.keys["agent_home"] == "h"
    assert registry.leader_mode.keys["agent_from_cl"] == "space"
    assert registry.app.focus_next_agent_panel == "J"
    assert registry.leader_mode.keys["jump_to_next_stopped_agent"] == "J"
    assert registry.leader_mode.keys["full_history_refresh"] == "y"
    assert registry.leader_mode.keys["mark_all_unread_done_agents_read"] == "u"

    bindings = build_app_bindings(registry.app)
    by_key = {b.key: b.action for b in bindings}
    assert by_key["a"] == "open_artifact_files"
    assert by_key["A"] == "accept_proposal"
    assert by_key["V"] == "show_agent_run_log"
    assert by_key["J"] == "focus_next_agent_panel"
    assert by_key["space"] == "start_agent_home"
    assert by_key["ctrl+@"] == "start_agent_from_patch"


def test_action_start_agent_home_opens_home_prompt() -> None:
    app = _FakeEntryPoints()

    app.action_start_agent_home()

    assert app.home_agent_count == 1


def test_leader_a_opens_agent_run_log_for_selected_cl() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha"), _make_cs("beta")])
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
    app = _FakeApp(changespecs=[_make_cs("alpha")], current_tab="agents")

    handled = app._handle_leader_key("A")

    assert handled is True
    assert app.refresh_count == 1
    assert app.pushed_modals == []


def test_leader_a_noops_with_empty_cls_list() -> None:
    app = _FakeApp(changespecs=[])

    handled = app._handle_leader_key("A")

    assert handled is True
    assert app.refresh_count == 1
    assert app.pushed_modals == []

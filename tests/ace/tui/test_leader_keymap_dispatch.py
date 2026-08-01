"""Tests for leader-mode key dispatch."""

from __future__ import annotations

import asyncio

from sase.ace.tui.actions.agents._unread_state import (
    BulkUnreadToggleOutcome,
    _BulkUnreadToggleResult,
)
from tests.ace.tui._leader_keymap_helpers import _FakeApp, _make_cs


def test_leader_space_runs_agent_from_current_cl() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha")])

    handled = app._handle_leader_key("space")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.quick_changespec_agent_count == 1
    assert app.quick_selected_agent_count == 0
    assert app.marked_agent_run_count == 0
    assert app._last_leader_key == "space"
    assert app.refresh_count == 1


def test_leader_question_mark_shows_help_on_all_tabs() -> None:
    for tab in ("changespecs", "agents", "axe"):
        app = _FakeApp(current_tab=tab)

        handled = app._handle_leader_key("question_mark")

        assert handled is True
        assert app._leader_mode_active is False
        assert app.show_help_count == 1
        assert app.notifications == []
        assert app._last_leader_key == "question_mark"
        assert app.refresh_count == 1


def test_leader_slash_edits_query_only_on_agents() -> None:
    app = _FakeApp(current_tab="agents")

    assert app._handle_leader_key("slash") is True
    assert app.edit_query_count == 1
    assert app._last_leader_key == "slash"
    assert app.refresh_count == 1

    for tab in ("changespecs", "axe"):
        app = _FakeApp(current_tab=tab)

        assert app._handle_leader_key("slash") is True
        assert app.edit_query_count == 0
        assert app._last_leader_key is None
        assert app.refresh_count == 1


def test_leader_query_repeat_rechecks_agents_context() -> None:
    app = _FakeApp(current_tab="agents")
    app._handle_leader_key("slash")
    app.current_tab = "changespecs"  # type: ignore[assignment]

    assert app._handle_leader_key("comma") is True
    assert app.edit_query_count == 1
    assert app._last_leader_key == "slash"
    assert app.refresh_count == 2


def test_leader_space_runs_agent_from_selected_agent_on_agents_tab() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("space")

    assert handled is True
    assert app.quick_selected_agent_count == 1
    assert app.quick_changespec_agent_count == 0
    assert app._last_leader_key == "space"


def test_leader_space_runs_agents_from_marked_cls() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha")])
    app.marked_indices = {0}

    handled = app._handle_leader_key("space")

    assert handled is True
    assert app.marked_agent_run_count == 1
    assert app.quick_changespec_agent_count == 0
    assert app._last_leader_key == "space"


def test_leader_h_runs_agent_home() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha")])

    handled = app._handle_leader_key("h")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.home_agent_count == 1
    assert app.quick_changespec_agent_count == 0
    assert app.quick_selected_agent_count == 0
    assert app.marked_agent_run_count == 0
    assert app._last_leader_key == "h"
    assert app.refresh_count == 1


def test_leader_ctrl_space_no_longer_runs_agent_from_current_cl() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha")])

    handled = app._handle_leader_key("ctrl+@")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.home_agent_count == 0
    assert app.quick_changespec_agent_count == 0
    assert app._last_leader_key is None
    assert app.refresh_count == 1


def test_leader_g_toggles_agent_panel_grouping_on_agents_tab() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("g")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.toggle_panel_grouping_count == 1
    assert app.refresh_count == 1


def test_leader_g_noops_on_non_agents_tabs() -> None:
    app = _FakeApp(current_tab="changespecs")

    handled = app._handle_leader_key("g")

    assert handled is True
    assert app.toggle_panel_grouping_count == 0
    assert app.refresh_count == 1


def test_leader_h_uppercase_no_longer_dispatches_selected_panel_toggle() -> None:
    app = _FakeApp(current_tab="agents")

    assert app._handle_leader_key("H") is True
    assert app.toggle_selected_panels_count == 0
    assert app.agent_footer_refresh_count == 0
    assert app.refresh_count == 1
    assert app._last_leader_key is None

    app._leader_mode_active = True
    assert app._handle_leader_key("comma") is True
    assert app.toggle_selected_panels_count == 0
    assert app.agent_footer_refresh_count == 0
    assert app.notifications == ["No leader command to repeat"]
    assert app.refresh_count == 2


def test_leader_h_uppercase_noops_on_non_agents_tabs() -> None:
    app = _FakeApp(current_tab="changespecs")

    assert app._handle_leader_key("H") is True
    assert app.toggle_selected_panels_count == 0


def test_leader_j_jumps_to_next_unread_done_agent_on_agents_tab() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("j")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.jump_unread_count == 1
    assert app.notifications == []
    assert app.refresh_count == 1


def test_leader_j_records_and_repeat_invokes_unread_jump_again() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("j")
    repeated = app._handle_leader_key("comma")

    assert handled is True
    assert repeated is True
    assert app.jump_unread_count == 2
    assert app._last_leader_key == "j"
    assert app.refresh_count == 2


def test_leader_repeat_without_previous_command_notifies_and_refreshes() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("comma")

    assert handled is True
    assert app._last_leader_key is None
    assert app.notifications == ["No leader command to repeat"]
    assert app.refresh_count == 1


def test_leader_unknown_key_and_escape_do_not_overwrite_previous_command() -> None:
    app = _FakeApp(current_tab="agents")
    app._handle_leader_key("j")

    app._handle_leader_key("unknown")
    app._handle_leader_key("escape")
    app._handle_leader_key("comma")

    assert app._last_leader_key == "j"
    assert app.jump_unread_count == 2
    assert app.refresh_count == 4


def test_leader_repeat_does_not_record_repeat_subkey() -> None:
    app = _FakeApp(current_tab="agents")

    app._handle_leader_key("j")
    app._handle_leader_key("comma")

    assert app._last_leader_key == "j"
    assert app.jump_unread_count == 2


def test_leader_r_reverts_selected_agent_on_agents_tab() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("r")

    assert handled is True
    assert app.retry_edit_count == 0
    assert app.runners_count == 0
    assert app.revert_count == 1
    assert app.refresh_count == 1


def test_leader_r_noops_on_non_agents_tabs() -> None:
    app = _FakeApp(current_tab="changespecs")

    handled = app._handle_leader_key("r")

    assert handled is True
    assert app.revert_count == 0
    assert app.refresh_count == 1


def test_leader_uppercase_r_opens_runners_on_agents_tab() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("R")

    assert handled is True
    assert app.retry_edit_count == 0
    assert app.revert_count == 0
    assert app.runners_count == 1
    assert app.refresh_count == 1


def test_leader_repeat_uses_raw_subkey_for_runners() -> None:
    app = _FakeApp(current_tab="agents")
    app._handle_leader_key("R")

    app.current_tab = "changespecs"  # type: ignore[assignment]
    app._handle_leader_key("comma")

    assert app._last_leader_key == "R"
    assert app.retry_edit_count == 0
    assert app.runners_count == 2


def test_leader_repeat_uses_raw_subkey_for_revert() -> None:
    app = _FakeApp(current_tab="agents")
    app._handle_leader_key("r")
    app._handle_leader_key("comma")

    assert app._last_leader_key == "r"
    assert app.revert_count == 2


def test_leader_x_kills_and_edits_focused_agent_without_marks() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("x")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.kill_and_edit_count == 1
    assert app.bulk_kill_and_edit_count == 0
    assert app._last_leader_key == "x"
    assert app.refresh_count == 1


def test_leader_x_kills_and_edits_marked_set_when_marks_exist() -> None:
    app = _FakeApp(current_tab="agents")
    app._marked_agents = {("running", "my_feature", None)}

    handled = app._handle_leader_key("x")

    assert handled is True
    assert app.bulk_kill_and_edit_count == 1
    assert app.kill_and_edit_count == 0
    assert app._last_leader_key == "x"
    assert app.refresh_count == 1


def test_leader_x_noops_on_non_agents_tabs() -> None:
    app = _FakeApp(current_tab="changespecs")
    app._marked_agents = {("running", "my_feature", None)}

    handled = app._handle_leader_key("x")

    assert handled is True
    assert app.kill_and_edit_count == 0
    assert app.bulk_kill_and_edit_count == 0
    assert app.refresh_count == 1


def test_leader_x_repeat_reevaluates_marks() -> None:
    app = _FakeApp(current_tab="agents")

    # First press with no marks routes to the focused-row flow.
    app._handle_leader_key("x")
    assert app.kill_and_edit_count == 1
    assert app.bulk_kill_and_edit_count == 0

    # Marks appear; repeating ,x remembers raw ``x`` and re-evaluates marks,
    # so the repeat routes to the bulk marked-set flow.
    app._marked_agents = {("running", "my_feature", None)}
    app._handle_leader_key("comma")

    assert app._last_leader_key == "x"
    assert app.bulk_kill_and_edit_count == 1
    assert app.kill_and_edit_count == 1


def test_leader_j_notifies_when_no_unread_done_agent() -> None:
    app = _FakeApp(current_tab="agents")
    app.jump_unread_result = False

    handled = app._handle_leader_key("j")

    assert handled is True
    assert app.jump_unread_count == 1
    assert app.notifications == ["No unread completed agents"]
    assert app.refresh_count == 1


def test_leader_j_noops_on_non_agents_tabs() -> None:
    app = _FakeApp(current_tab="changespecs")

    handled = app._handle_leader_key("j")

    assert handled is True
    assert app.jump_unread_count == 0
    assert app.notifications == []
    assert app.refresh_count == 1


def test_leader_shift_j_jumps_to_next_stopped_agent_on_agents_tab() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("J")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.jump_stopped_count == 1
    assert app.mark_all_unread_count == 0
    assert app.notifications == []
    assert app.refresh_count == 1


def test_leader_shift_j_notifies_when_no_stopped_agents() -> None:
    app = _FakeApp(current_tab="agents")
    app.jump_stopped_result = False

    handled = app._handle_leader_key("J")

    assert handled is True
    assert app.jump_stopped_count == 1
    assert app.notifications == ["No stopped agents"]
    assert app.refresh_count == 1


def test_leader_shift_j_noops_on_non_agents_tabs() -> None:
    app = _FakeApp(current_tab="changespecs")

    handled = app._handle_leader_key("J")

    assert handled is True
    assert app.mark_all_unread_count == 0
    assert app.jump_stopped_count == 0
    assert app.notifications == []
    assert app.refresh_count == 1


def test_leader_y_refreshes_agents_from_full_history() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("y")

    assert handled is True
    assert app.full_history_refresh_count == 1
    assert app.refresh_count == 1


def test_leader_y_noops_on_non_agents_tabs() -> None:
    app = _FakeApp(current_tab="changespecs")

    handled = app._handle_leader_key("y")

    assert handled is True
    assert app.full_history_refresh_count == 0
    assert app.refresh_count == 1


def test_leader_u_marks_all_unread_done_agents_read_on_agents_tab() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("u")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.mark_all_unread_count == 1
    assert app.notifications == ["Marked 2 completed agents read"]
    assert app.refresh_count == 0


def test_leader_u_notifies_when_no_unread_done_agents() -> None:
    app = _FakeApp(current_tab="agents")
    app.mark_all_unread_result = _BulkUnreadToggleResult(BulkUnreadToggleOutcome.NOOP)

    handled = app._handle_leader_key("u")

    assert handled is True
    assert app.mark_all_unread_count == 1
    assert app.notifications == ["No unread completed agents"]
    assert app.refresh_count == 1


def test_leader_u_notifies_when_bulk_read_is_restored() -> None:
    app = _FakeApp(current_tab="agents")
    app.mark_all_unread_result = _BulkUnreadToggleResult(
        BulkUnreadToggleOutcome.RESTORED_UNREAD,
        2,
    )

    handled = app._handle_leader_key("u")

    assert handled is True
    assert app.mark_all_unread_count == 1
    assert app.notifications == ["Restored 2 completed agents unread"]
    assert app.refresh_count == 0


def test_leader_u_records_and_repeat_invokes_bulk_toggle_again() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("u")
    app.mark_all_unread_result = _BulkUnreadToggleResult(
        BulkUnreadToggleOutcome.RESTORED_UNREAD,
        2,
    )
    repeated = app._handle_leader_key("comma")

    assert handled is True
    assert repeated is True
    assert app.mark_all_unread_count == 2
    assert app._last_leader_key == "u"
    assert app.notifications == [
        "Marked 2 completed agents read",
        "Restored 2 completed agents unread",
    ]
    assert app.refresh_count == 0


def test_leader_uppercase_u_opens_sase_update_shortcut() -> None:
    app = _FakeApp(current_tab="axe")

    handled = app._handle_leader_key("U")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.update_sase_shortcut_count == 1
    assert app._last_leader_key == "U"
    assert app.refresh_count == 1


def test_leader_at_schedules_panel_only_action_and_repeat() -> None:
    app = _FakeApp(current_tab="axe")

    handled = app._handle_leader_key("at")

    assert handled is True
    assert app._leader_mode_active is False
    assert app._last_leader_key == "at"
    assert app.scheduled_callbacks == [app.action_open_prompt_stash]
    assert app.refresh_count == 1

    asyncio.run(app.scheduled_callbacks.pop()())
    assert app.open_prompt_stash_count == 1

    repeated = app._handle_leader_key("comma")
    assert repeated is True
    assert app._last_leader_key == "at"
    assert app.scheduled_callbacks == [app.action_open_prompt_stash]
    assert app.refresh_count == 2


def test_leader_ctrl_g_edits_first_prompt_history_entry() -> None:
    app = _FakeApp()

    handled = app._handle_leader_key("ctrl+g")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.prompt_history_calls == [{"show_cancelled": False, "edit_first": True}]
    assert app.refresh_count == 1

"""Leader dispatch: launch, revert, kill-and-edit, and fold-collapse keys.

Split from ``test_leader_keymap_dispatch``; see that module for the facade.
"""

from __future__ import annotations

from tests.ace.tui._leader_keymap_helpers import FakeApp, make_cs


def test_leader_space_runs_agent_from_current_cl() -> None:
    app = FakeApp(patches=[make_cs("alpha")])

    handled = app._handle_leader_key("space")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.quick_patch_agent_count == 1
    assert app.quick_selected_agent_count == 0
    assert app.marked_agent_run_count == 0
    assert app._last_leader_key == "space"
    assert app.refresh_count == 1


def test_leader_space_runs_agent_from_selected_agent_on_agents_tab() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("space")

    assert handled is True
    assert app.quick_selected_agent_count == 1
    assert app.quick_patch_agent_count == 0
    assert app._last_leader_key == "space"


def test_leader_space_runs_agents_from_marked_cls() -> None:
    app = FakeApp(patches=[make_cs("alpha")])
    app.marked_indices = {0}

    handled = app._handle_leader_key("space")

    assert handled is True
    assert app.marked_agent_run_count == 1
    assert app.quick_patch_agent_count == 0
    assert app._last_leader_key == "space"


def test_leader_h_runs_agent_home() -> None:
    app = FakeApp(patches=[make_cs("alpha")])

    handled = app._handle_leader_key("h")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.home_agent_count == 1
    assert app.quick_patch_agent_count == 0
    assert app.quick_selected_agent_count == 0
    assert app.marked_agent_run_count == 0
    assert app._last_leader_key == "h"
    assert app.refresh_count == 1


def test_leader_k_starts_hijack_only_on_agents_tab() -> None:
    app = FakeApp(current_tab="agents")
    calls: list[str] = []
    app._start_hijack_agent = lambda: calls.append("hijack")  # type: ignore[attr-defined]

    assert app._handle_leader_key("k") is True
    assert calls == ["hijack"]
    assert app._last_leader_key == "k"

    app = FakeApp(current_tab="patches")
    app._start_hijack_agent = lambda: calls.append("unexpected")  # type: ignore[attr-defined]
    assert app._handle_leader_key("k") is True
    assert calls == ["hijack"]


def test_leader_ctrl_space_no_longer_runs_agent_from_current_cl() -> None:
    app = FakeApp(patches=[make_cs("alpha")])

    handled = app._handle_leader_key("ctrl+@")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.home_agent_count == 0
    assert app.quick_patch_agent_count == 0
    assert app._last_leader_key is None
    assert app.refresh_count == 1


def test_leader_r_reverts_selected_agent_on_agents_tab() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("r")

    assert handled is True
    assert app.retry_edit_count == 0
    assert app.runners_count == 0
    assert app.revert_count == 1
    assert app.refresh_count == 1


def test_leader_r_noops_on_non_agents_tabs() -> None:
    app = FakeApp(current_tab="patches")

    handled = app._handle_leader_key("r")

    assert handled is True
    assert app.revert_count == 0
    assert app.refresh_count == 1


def test_leader_uppercase_r_opens_runners_on_agents_tab() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("R")

    assert handled is True
    assert app.retry_edit_count == 0
    assert app.revert_count == 0
    assert app.runners_count == 1
    assert app.refresh_count == 1


def test_leader_repeat_uses_raw_subkey_for_runners() -> None:
    app = FakeApp(current_tab="agents")
    app._handle_leader_key("R")

    app.current_tab = "patches"  # type: ignore[assignment]
    app._handle_leader_key("comma")

    assert app._last_leader_key == "R"
    assert app.retry_edit_count == 0
    assert app.runners_count == 2


def test_leader_repeat_uses_raw_subkey_for_revert() -> None:
    app = FakeApp(current_tab="agents")
    app._handle_leader_key("r")
    app._handle_leader_key("comma")

    assert app._last_leader_key == "r"
    assert app.revert_count == 2


def test_leader_x_kills_and_edits_focused_agent_without_marks() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("x")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.kill_and_edit_count == 1
    assert app.bulk_kill_and_edit_count == 0
    assert app._last_leader_key == "x"
    assert app.refresh_count == 1


def test_leader_x_kills_and_edits_marked_set_when_marks_exist() -> None:
    app = FakeApp(current_tab="agents")
    app._marked_agents = {("running", "my_feature", None)}

    handled = app._handle_leader_key("x")

    assert handled is True
    assert app.bulk_kill_and_edit_count == 1
    assert app.kill_and_edit_count == 0
    assert app._last_leader_key == "x"
    assert app.refresh_count == 1


def test_leader_x_noops_on_non_agents_tabs() -> None:
    app = FakeApp(current_tab="patches")
    app._marked_agents = {("running", "my_feature", None)}

    handled = app._handle_leader_key("x")

    assert handled is True
    assert app.kill_and_edit_count == 0
    assert app.bulk_kill_and_edit_count == 0
    assert app.refresh_count == 1


def test_leader_x_repeat_reevaluates_marks() -> None:
    app = FakeApp(current_tab="agents")

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


def test_leader_shift_x_targets_last_launch_ignoring_marks() -> None:
    app = FakeApp(current_tab="agents")
    app._marked_agents = {("running", "my_feature", None)}

    handled = app._handle_leader_key("X")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.kill_and_edit_last_count == 1
    assert app.kill_and_edit_count == 0
    assert app.bulk_kill_and_edit_count == 0
    assert app._last_leader_key == "X"
    assert app.refresh_count == 1


def test_leader_shift_x_noops_on_non_agents_tabs() -> None:
    app = FakeApp(current_tab="patches")

    handled = app._handle_leader_key("X")

    assert handled is True
    assert app.kill_and_edit_last_count == 0
    assert app.refresh_count == 1


def test_leader_h_uppercase_dispatches_collapse_fold_by_hint() -> None:
    app = FakeApp(current_tab="agents")

    assert app._handle_leader_key("H") is True
    assert app.collapse_fold_by_hint_count == 1
    assert app.toggle_selected_panels_count == 0
    assert app._last_leader_key == "H"
    assert app.agent_footer_refresh_count == 1
    assert app.refresh_count == 0

    app._leader_mode_active = True
    assert app._handle_leader_key("comma") is True
    assert app.collapse_fold_by_hint_count == 2
    assert app.toggle_selected_panels_count == 0
    assert app.agent_footer_refresh_count == 2


def test_leader_h_uppercase_skips_footer_refresh_when_hint_mode_arms() -> None:
    app = FakeApp(current_tab="agents")
    app.arm_hint_on_collapse = True

    assert app._handle_leader_key("H") is True
    assert app.collapse_fold_by_hint_count == 1
    assert app._panel_fold_hint_mode_active is True
    assert app.agent_footer_refresh_count == 0
    assert app.refresh_count == 0
    assert app.toggle_selected_panels_count == 0


def test_leader_h_uppercase_noops_on_non_agents_tabs() -> None:
    app = FakeApp(current_tab="patches")

    assert app._handle_leader_key("H") is True
    assert app.collapse_fold_by_hint_count == 0
    assert app.toggle_selected_panels_count == 0
    assert app.refresh_count == 1

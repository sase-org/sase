"""Tests for the leader ``,A`` Agent Run Log fallback keymap."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
from sase.ace.tui.actions.changespec._core import ChangeSpecMixin
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.modals.agent_run_log_modal import AgentRunLogModal
from sase.ace.tui.widgets import KeybindingFooter


class _FakeApp(LeaderModeMixin, ChangeSpecMixin):
    """Minimal app stand-in for leader dispatch."""

    def __init__(
        self,
        *,
        changespecs: list[Any] | None = None,
        current_tab: str = "changespecs",
    ) -> None:
        self.changespecs = changespecs or []
        self.current_idx = 0
        self.current_tab = current_tab  # type: ignore[assignment]
        self.marked_indices = set()
        self._agents = []
        self._leader_mode_active = True
        self._last_leader_key: str | None = None
        self._keymap_registry = load_keymap_registry({})
        self.pushed_modals: list[Any] = []
        self.notifications: list[str] = []
        self.refresh_count = 0
        self.toggle_panel_grouping_count = 0
        self.retry_edit_count = 0
        self.runners_count = 0
        self.jump_unread_count = 0
        self.jump_unread_result = True
        self.jump_stopped_count = 0
        self.jump_stopped_result = True
        self.full_history_refresh_count = 0
        self.mark_all_unread_count = 0
        self.mark_all_unread_result = 2
        self.prompt_history_calls: list[dict[str, bool]] = []
        self.home_agent_count = 0
        self.quick_changespec_agent_count = 0
        self.quick_selected_agent_count = 0
        self.marked_agent_run_count = 0

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        del callback
        self.pushed_modals.append(modal)

    def notify(self, message: str, **_: Any) -> None:
        self.notifications.append(message)

    def _refresh_current_tab(self) -> None:
        self.refresh_count += 1

    def action_toggle_agent_panel_grouping(self) -> None:
        self.toggle_panel_grouping_count += 1

    def _retry_edit_agent(self) -> None:
        self.retry_edit_count += 1

    def action_show_runners(self) -> None:
        self.runners_count += 1

    def _jump_to_next_unread_done_agent(self) -> bool:
        self.jump_unread_count += 1
        return self.jump_unread_result

    def _jump_to_next_stopped_agent(self) -> bool:
        self.jump_stopped_count += 1
        return self.jump_stopped_result

    def action_refresh_agents_full_history(self) -> None:
        self.full_history_refresh_count += 1

    def _mark_all_unread_done_agents_read(self) -> int:
        self.mark_all_unread_count += 1
        return self.mark_all_unread_result

    def _start_prompt_history_from_last_selection(
        self,
        *,
        show_cancelled: bool = False,
        edit_first: bool = False,
    ) -> None:
        self.prompt_history_calls.append(
            {"show_cancelled": show_cancelled, "edit_first": edit_first}
        )

    def _show_prompt_input_bar_for_home(self) -> None:
        self.home_agent_count += 1

    def _start_agent_from_changespec_quick(self) -> None:
        self.quick_changespec_agent_count += 1

    def _start_agent_from_agent_quick(self) -> None:
        self.quick_selected_agent_count += 1

    def _start_agents_from_marked(self) -> None:
        self.marked_agent_run_count += 1


def _make_cs(name: str) -> MagicMock:
    cs = MagicMock()
    cs.name = name
    return cs


def test_default_keymap_binds_v_to_agent_run_log_and_a_to_artifacts() -> None:
    registry = load_keymap_registry({})

    assert registry.app.show_agent_run_log == "V"
    assert registry.app.open_agent_artifacts == "A"
    assert registry.app.start_agent_from_changespec == "ctrl+@"
    assert registry.leader_mode.keys["agent_run_log"] == "A"
    assert registry.leader_mode.keys["agent_home"] == "space"
    assert registry.leader_mode.keys["agent_from_cl"] == "ctrl+@"
    assert registry.app.focus_next_agent_panel == "J"
    assert registry.leader_mode.keys["jump_to_next_stopped_agent"] == "J"
    assert registry.leader_mode.keys["full_history_refresh"] == "y"
    assert registry.leader_mode.keys["mark_all_unread_done_agents_read"] == "u"

    bindings = build_app_bindings(registry.app)
    by_key = {b.key: b.action for b in bindings}
    assert by_key["A"] == "open_agent_artifacts"
    assert by_key["V"] == "show_agent_run_log"
    assert by_key["J"] == "focus_next_agent_panel"
    assert by_key["ctrl+@"] == "start_agent_from_changespec"
    assert "space" not in by_key


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


def test_leader_ctrl_space_runs_agent_from_current_cl() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha")])

    handled = app._handle_leader_key("ctrl+@")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.quick_changespec_agent_count == 1
    assert app.quick_selected_agent_count == 0
    assert app.marked_agent_run_count == 0
    assert app._last_leader_key == "ctrl+@"
    assert app.refresh_count == 1


def test_leader_ctrl_space_runs_agent_from_selected_agent_on_agents_tab() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("ctrl+@")

    assert handled is True
    assert app.quick_selected_agent_count == 1
    assert app.quick_changespec_agent_count == 0
    assert app._last_leader_key == "ctrl+@"


def test_leader_ctrl_space_runs_agents_from_marked_cls() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha")])
    app.marked_indices = {0}

    handled = app._handle_leader_key("ctrl+@")

    assert handled is True
    assert app.marked_agent_run_count == 1
    assert app.quick_changespec_agent_count == 0
    assert app._last_leader_key == "ctrl+@"


def test_leader_space_runs_agent_home() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha")])

    handled = app._handle_leader_key("space")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.home_agent_count == 1
    assert app.quick_changespec_agent_count == 0
    assert app.quick_selected_agent_count == 0
    assert app.marked_agent_run_count == 0
    assert app._last_leader_key == "space"
    assert app.refresh_count == 1


def test_leader_h_no_longer_runs_agent_home() -> None:
    app = _FakeApp(changespecs=[_make_cs("alpha")])

    handled = app._handle_leader_key("h")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.home_agent_count == 0
    assert app._last_leader_key is None
    assert app.refresh_count == 1


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


def test_leader_r_opens_runners_on_agents_tab() -> None:
    app = _FakeApp(current_tab="agents")

    handled = app._handle_leader_key("r")

    assert handled is True
    assert app.retry_edit_count == 0
    assert app.runners_count == 1
    assert app.refresh_count == 1


def test_leader_repeat_uses_raw_subkey_for_runners() -> None:
    app = _FakeApp(current_tab="agents")
    app._handle_leader_key("r")

    app.current_tab = "changespecs"  # type: ignore[assignment]
    app._handle_leader_key("comma")

    assert app._last_leader_key == "r"
    assert app.retry_edit_count == 0
    assert app.runners_count == 2


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
    app.mark_all_unread_result = 0

    handled = app._handle_leader_key("u")

    assert handled is True
    assert app.mark_all_unread_count == 1
    assert app.notifications == ["No unread completed agents"]
    assert app.refresh_count == 1


def test_leader_ctrl_g_edits_first_prompt_history_entry() -> None:
    app = _FakeApp()

    handled = app._handle_leader_key("ctrl+g")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.prompt_history_calls == [{"show_cancelled": False, "edit_first": True}]
    assert app.refresh_count == 1


def _capture_bindings(
    footer: KeybindingFooter,
) -> list[tuple[list[tuple[str, str]], str | None]]:
    """Replace ``_update_display`` with a recorder for the bindings/mode args."""
    captured: list[tuple[list[tuple[str, str]], str | None]] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda bindings, mode_label=None: captured.append(
            (list(bindings), mode_label)
        )
    )
    return captured


def _last_keys(captured: list[tuple[list[tuple[str, str]], str | None]]) -> set[str]:
    return {k for k, _ in captured[-1][0]}


def _last_labels(captured: list[tuple[list[tuple[str, str]], str | None]]) -> set[str]:
    return {label for _, label in captured[-1][0]}


def test_footer_surfaces_agent_run_log_only_on_cls_tab() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="changespecs")
    assert "A" in _last_keys(captured)
    assert "agent run log" in _last_labels(captured)

    for tab in ("agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "agent run log" not in _last_labels(captured)


def test_footer_surfaces_panel_grouping_only_on_agents_tab() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="agents")
    assert "g" in _last_keys(captured)
    assert "group panels" in _last_labels(captured)

    footer.update_leader_bindings(current_tab="changespecs")
    assert "group panels" not in _last_labels(captured)


def test_footer_surfaces_repeat_last_on_all_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "," in _last_keys(captured)
        assert "repeat" in _last_labels(captured)


def test_footer_surfaces_agent_home_as_space_on_all_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert ("<space>", "agent (home)") in captured[-1][0]
        assert ("h", "agent (home)") not in captured[-1][0]


def test_footer_surfaces_project_management_on_all_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "p" in _last_keys(captured)
        assert "projects" in _last_labels(captured)


def test_footer_surfaces_ctrl_space_run_agent_on_cl_and_agents_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("changespecs", "agents"):
        footer.update_leader_bindings(current_tab=tab)
        assert "Ctrl+Space" in _last_keys(captured)
        assert "run agent (CL)" in _last_labels(captured)

    footer.update_leader_bindings(current_tab="axe")
    assert "run agent (CL)" not in _last_labels(captured)


def test_footer_surfaces_configured_repeat_last_key() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(
        load_keymap_registry(
            {"keymaps": {"modes": {"leader_mode": {"keys": {"repeat_last": "R"}}}}}
        )
    )
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="agents")

    assert "R" in _last_keys(captured)
    assert "repeat" in _last_labels(captured)


def test_footer_surfaces_unread_done_jump_only_when_available() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="agents", has_unread_completed_agent=True)
    assert "j" in _last_keys(captured)
    assert "next unread done" in _last_labels(captured)
    assert "u" in _last_keys(captured)
    assert "mark all read" in _last_labels(captured)

    footer.update_leader_bindings(
        current_tab="agents", has_unread_completed_agent=False
    )
    assert "next unread done" not in _last_labels(captured)
    assert "mark all read" not in _last_labels(captured)


def test_footer_surfaces_stopped_jump_only_when_available() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    footer.update_leader_bindings(current_tab="agents", has_stopped_agent=True)
    assert "J" in _last_keys(captured)
    assert "next stopped" in _last_labels(captured)

    footer.update_leader_bindings(current_tab="agents", has_stopped_agent=False)
    assert "next stopped" not in _last_labels(captured)

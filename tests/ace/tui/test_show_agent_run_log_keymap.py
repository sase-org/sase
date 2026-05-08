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
        self._keymap_registry = load_keymap_registry({})
        self.pushed_modals: list[Any] = []
        self.notifications: list[str] = []
        self.refresh_count = 0
        self.toggle_panel_grouping_count = 0
        self.jump_unread_count = 0
        self.jump_unread_result = True

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        del callback
        self.pushed_modals.append(modal)

    def notify(self, message: str, **_: Any) -> None:
        self.notifications.append(message)

    def _refresh_current_tab(self) -> None:
        self.refresh_count += 1

    def action_toggle_agent_panel_grouping(self) -> None:
        self.toggle_panel_grouping_count += 1

    def _jump_to_next_unread_done_agent(self) -> bool:
        self.jump_unread_count += 1
        return self.jump_unread_result


def _make_cs(name: str) -> MagicMock:
    cs = MagicMock()
    cs.name = name
    return cs


def test_default_keymap_binds_v_to_agent_run_log_and_a_to_artifacts() -> None:
    registry = load_keymap_registry({})

    assert registry.app.show_agent_run_log == "V"
    assert registry.app.open_agent_artifacts == "A"
    assert registry.leader_mode.keys["agent_run_log"] == "A"

    bindings = build_app_bindings(registry.app)
    by_key = {b.key: b.action for b in bindings}
    assert by_key["A"] == "open_agent_artifacts"
    assert by_key["V"] == "show_agent_run_log"


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


def test_footer_surfaces_agent_run_log_only_on_cls_tab() -> None:
    footer = KeybindingFooter()
    captured: list[object] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda text: captured.append(text)
    )

    footer.update_leader_bindings(current_tab="changespecs")
    rendered = str(captured[-1])
    assert "A" in rendered
    assert "agent run log" in rendered

    for tab in ("agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "agent run log" not in str(captured[-1])


def test_footer_surfaces_panel_grouping_only_on_agents_tab() -> None:
    footer = KeybindingFooter()
    captured: list[object] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda text: captured.append(text)
    )

    footer.update_leader_bindings(current_tab="agents")
    rendered = str(captured[-1])
    assert "g" in rendered
    assert "group panels" in rendered

    footer.update_leader_bindings(current_tab="changespecs")
    assert "group panels" not in str(captured[-1])


def test_footer_surfaces_unread_done_jump_only_when_available() -> None:
    footer = KeybindingFooter()
    captured: list[object] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda text: captured.append(text)
    )

    footer.update_leader_bindings(current_tab="agents", has_unread_completed_agent=True)
    rendered = str(captured[-1])
    assert "j" in rendered
    assert "next unread done" in rendered

    footer.update_leader_bindings(
        current_tab="agents", has_unread_completed_agent=False
    )
    assert "next unread done" not in str(captured[-1])

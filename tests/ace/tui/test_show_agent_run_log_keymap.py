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
        self.refresh_count = 0
        self.toggle_panel_grouping_count = 0

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        del callback
        self.pushed_modals.append(modal)

    def _refresh_current_tab(self) -> None:
        self.refresh_count += 1

    def action_toggle_agent_panel_grouping(self) -> None:
        self.toggle_panel_grouping_count += 1


def _make_cs(name: str) -> MagicMock:
    cs = MagicMock()
    cs.name = name
    return cs


def test_default_keymap_binds_a_to_agent_run_log() -> None:
    registry = load_keymap_registry({})

    assert registry.app.show_agent_run_log == "A"
    assert registry.leader_mode.keys["agent_run_log"] == "A"

    bindings = build_app_bindings(registry.app)
    matches = [b for b in bindings if b.key == "A"]
    assert len(matches) == 1
    assert matches[0].action == "show_agent_run_log"


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

"""Tests for the leader ``,A`` Agent Run Log fallback keymap."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
from sase.ace.tui.actions.changespec._core import ChangeSpecMixin
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.modals.agent_run_log_modal import AgentRunLogModal
from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal
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

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        del callback
        self.pushed_modals.append(modal)

    def _refresh_current_tab(self) -> None:
        self.refresh_count += 1


def _make_cs(name: str) -> MagicMock:
    cs = MagicMock()
    cs.name = name
    return cs


def test_default_keymap_keeps_app_a_artifacts_and_leader_a_run_log() -> None:
    registry = load_keymap_registry({})

    assert registry.app.open_artifacts_panel == "A"
    assert registry.leader_mode.keys["agent_run_log"] == "A"

    bindings = build_app_bindings(registry.app)
    matches = [b for b in bindings if b.key == "A"]
    assert len(matches) == 1
    assert matches[0].action == "open_artifacts_panel"
    assert all(
        binding[1] != "open_legacy_run_log" for binding in ArtifactPanelModal.BINDINGS
    )


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

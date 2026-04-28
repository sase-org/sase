"""Tests for the `A` keymap that opens the Agent Run Log modal."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.changespec import ChangeSpecMixin
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.modals.agent_run_log_modal import AgentRunLogModal


class _FakeApp(ChangeSpecMixin):
    """Minimal app stand-in capturing pushed modals."""

    def __init__(
        self, changespecs: list[Any], current_tab: str = "changespecs"
    ) -> None:
        self.changespecs: list = changespecs  # type: ignore[assignment]
        self.current_idx: int = 0
        self.current_tab = current_tab  # type: ignore[assignment]
        self.pushed_modals: list[Any] = []

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        del callback
        self.pushed_modals.append(modal)


def _make_cs(name: str) -> MagicMock:
    cs = MagicMock()
    cs.name = name
    return cs


def test_show_agent_run_log_opens_modal_for_current_changespec() -> None:
    """`A` on the CLs tab pushes AgentRunLogModal for the selected ChangeSpec."""
    app = _FakeApp([_make_cs("alpha"), _make_cs("beta")])
    app.current_idx = 1

    app.action_show_agent_run_log()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentRunLogModal)
    assert modal._cl_name == "beta"


def test_show_agent_run_log_no_op_on_other_tabs() -> None:
    """`A` outside the CLs tab does nothing."""
    for tab in ("agents", "axe"):
        app = _FakeApp([_make_cs("alpha")], current_tab=tab)
        app.action_show_agent_run_log()
        assert app.pushed_modals == []


def test_show_agent_run_log_no_op_when_no_changespecs() -> None:
    """`A` is a no-op when the CL list is empty."""
    app = _FakeApp([])
    app.action_show_agent_run_log()
    assert app.pushed_modals == []


def test_default_keymap_binds_capital_a_to_show_agent_run_log() -> None:
    """default_config.yml maps `A` to the show_agent_run_log action."""
    registry = load_keymap_registry({"keymaps": {"app": {}}})
    assert registry.app.show_agent_run_log == "A"

    bindings = build_app_bindings(registry.app)
    matches = [b for b in bindings if b.action == "show_agent_run_log"]
    assert len(matches) == 1
    assert matches[0].key == "A"

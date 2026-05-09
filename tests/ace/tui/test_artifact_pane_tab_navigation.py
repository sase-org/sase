from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin


class _TabNavigationApp(BasicNavigationMixin):
    def __init__(
        self,
        *,
        current_tab: str = "agents",
        focus_result: bool = False,
    ) -> None:
        self.current_tab: Any = current_tab
        self.current_idx = 0
        self.changespecs = [SimpleNamespace(name="cl")]
        self._agents = []
        self._axe_items = []
        self._changespecs_last_idx = 0
        self._changespecs_last_name = None
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._axe_last_idx = 0
        self._axe_last_item_key = None
        self.focus_result = focus_result
        self.focus_calls = 0
        self.activity_calls = 0

    def _record_user_activity(self) -> None:
        self.activity_calls += 1

    def _focus_tracked_artifact_tmux_pane(self) -> bool:
        self.focus_calls += 1
        return self.focus_result


def test_next_tab_focuses_live_artifact_pane_and_stays_on_agents() -> None:
    app = _TabNavigationApp(current_tab="agents", focus_result=True)

    app.action_next_tab()

    assert app.current_tab == "agents"
    assert app.focus_calls == 1
    assert app.activity_calls == 1


def test_next_tab_switches_from_agents_when_no_live_artifact_pane() -> None:
    app = _TabNavigationApp(current_tab="agents", focus_result=False)

    app.action_next_tab()

    assert app.current_tab == "axe"
    assert app.focus_calls == 1
    assert app.activity_calls == 1


def test_next_tab_keeps_normal_behavior_on_non_agents_tabs() -> None:
    app = _TabNavigationApp(current_tab="changespecs", focus_result=True)

    app.action_next_tab()

    assert app.current_tab == "agents"
    assert app.focus_calls == 0
    assert app.activity_calls == 1

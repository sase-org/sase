"""The Agents non-run toggle moved from `.` to `I`.

``I`` (``toggle_hide_non_run_agents``) flips ``hide_non_run_agents`` on the
Agents tab and is a no-op elsewhere; ``.`` (``toggle_hide_reverted``) no
longer touches Agents state and still toggles axe commands on Services.
"""

from __future__ import annotations

from sase.ace.tui.actions.agents._filter_actions import AgentFilterActionsMixin
from sase.ace.tui.actions.patch._core import PatchMixin


class _ToggleApp(AgentFilterActionsMixin, PatchMixin):
    def __init__(self, *, tab: str) -> None:
        self.current_tab = tab
        self.hide_non_run_agents = False
        self._agent_search_query = ""
        self._agent_search_query_seeded = True
        self.refilter_calls = 0
        self.async_refresh_calls: list[str] = []
        self._axe_cmds_hidden = False
        self._axe_items: list[object] = []
        self.current_idx = 0
        self.rebuilt_axe = 0
        self.refreshed_axe = 0

    def _refilter_agents(self) -> None:
        self.refilter_calls += 1

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        self.async_refresh_calls.append(source)

    def _build_axe_items(self) -> None:
        self.rebuilt_axe += 1

    def _refresh_axe_display(self) -> None:
        self.refreshed_axe += 1


def test_capital_i_toggles_hide_non_run_agents_on_agents() -> None:
    app = _ToggleApp(tab="agents")

    app.action_toggle_hide_non_run_agents()

    assert app.hide_non_run_agents is True
    assert app.refilter_calls == 1
    assert app.async_refresh_calls == ["filter"]


def test_capital_i_is_noop_off_agents() -> None:
    app = _ToggleApp(tab="services")

    app.action_toggle_hide_non_run_agents()

    assert app.hide_non_run_agents is False
    assert app.refilter_calls == 0
    assert app.async_refresh_calls == []


def test_dot_no_longer_toggles_non_run_agents() -> None:
    app = _ToggleApp(tab="agents")

    app.action_toggle_hide_reverted()

    assert app.hide_non_run_agents is False
    assert app.refilter_calls == 0
    assert app.async_refresh_calls == []


def test_dot_still_toggles_axe_commands_on_services() -> None:
    app = _ToggleApp(tab="services")

    app.action_toggle_hide_reverted()

    assert app._axe_cmds_hidden is True
    assert app.rebuilt_axe == 1
    assert app.refreshed_axe == 1
    assert app.hide_non_run_agents is False

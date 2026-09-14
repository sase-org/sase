"""Availability tests for the Agents-tab `V` metadata pager action.

Covers the tab-disjoint split introduced alongside `view_agent_metadata`:
`V` opens the metadata pager on the Agents tab (only for a local, selected
row) and keeps opening the Agent Run Log modal everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.tui._app_action_availability import (
    _LOCAL_AGENT_ROW_ACTIONS,
    check_app_action,
)
from tests.ace.agent_artifact_startup_fixtures import make_agent


def _fallback(_action: str, _parameters: tuple[object, ...]) -> bool:
    return True


@dataclass
class _FakeApp:
    current_tab: str
    _selected_agent: Any = None
    current_artifacts_pane_key: str = "patches"

    def _get_selected_agent(self) -> Any:
        return self._selected_agent


def _check(app: _FakeApp, action: str) -> bool | None:
    return check_app_action(app, action, (), _fallback)


def test_view_agent_metadata_available_for_local_agents_row() -> None:
    agent = make_agent(status="RUNNING")
    app = _FakeApp(current_tab="agents", _selected_agent=agent)

    assert _check(app, "view_agent_metadata") is True


def test_view_agent_metadata_unavailable_without_selection() -> None:
    app = _FakeApp(current_tab="agents", _selected_agent=None)

    assert _check(app, "view_agent_metadata") is False


def test_view_agent_metadata_unavailable_for_remote_fleet_row() -> None:
    agent = make_agent(status="RUNNING")
    agent.fleet_origin_alias = "remote-host"
    app = _FakeApp(current_tab="agents", _selected_agent=agent)

    assert _check(app, "view_agent_metadata") is False


def test_view_agent_metadata_unavailable_on_other_tabs() -> None:
    agent = make_agent(status="RUNNING")
    app = _FakeApp(current_tab="artifacts", _selected_agent=agent)

    assert _check(app, "view_agent_metadata") is False


def test_show_agent_run_log_disabled_on_agents_tab() -> None:
    agent = make_agent(status="RUNNING")
    app = _FakeApp(current_tab="agents", _selected_agent=agent)

    assert _check(app, "show_agent_run_log") is False


def test_show_agent_run_log_still_available_on_patches_tab() -> None:
    app = _FakeApp(current_tab="artifacts", _selected_agent=None)

    assert _check(app, "show_agent_run_log") is True


def test_local_agent_row_actions_membership() -> None:
    assert "view_agent_metadata" in _LOCAL_AGENT_ROW_ACTIONS
    assert "show_agent_run_log" not in _LOCAL_AGENT_ROW_ACTIONS

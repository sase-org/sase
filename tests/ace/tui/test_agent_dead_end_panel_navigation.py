"""Lowercase j/k escape from tribe panels with no other selectable row."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents._panel_types import (
    ARTIFACT_FILE_VIEWER_NAV_MESSAGE,
)
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.agent import Agent

from ._agent_panel_collapse_helpers import AgentPanelCollapseApp, make_agent


class _DeadEndNavigationApp(BasicNavigationMixin, AgentPanelCollapseApp):
    """Panel-collapse harness with production lowercase j/k navigation."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        focused_key: str | None = None,
        merged: bool = False,
    ) -> None:
        AgentPanelCollapseApp.__init__(
            self,
            agents,
            focused_key=focused_key,
            merged=merged,
        )
        self.artifact_file_viewer_guard_active = False

    def _refresh_agents_display_debounced(self) -> None:
        self._refresh_agents_display(list_changed=False)

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        if not self.artifact_file_viewer_guard_active:
            return False
        self.notify(ARTIFACT_FILE_VIEWER_NAV_MESSAGE, severity="warning")
        return True


class _ZeroStopNavigationApp(_DeadEndNavigationApp):
    """Dead-end harness whose focused expanded panel renders no rows."""

    def _panel_navigation_stops(
        self,
        *,
        include_panel_focus: bool = False,
    ) -> list[tuple[str, int | tuple[str, ...]]]:
        del include_panel_focus
        return []


def _single_row_panels() -> list[Agent]:
    return [
        make_agent(name="default", project="default", tribe=None),
        make_agent(name="alpha", project="alpha", tribe="alpha"),
        make_agent(name="beta", project="beta", tribe="beta"),
    ]


@pytest.mark.parametrize(
    ("direction", "expected_panel_idx", "expected_agent_idx"),
    [
        (1, 2, 2),
        (-1, 0, 0),
    ],
)
def test_lone_row_selects_adjacent_whole_panel(
    direction: int,
    expected_panel_idx: int,
    expected_agent_idx: int,
) -> None:
    agents = _single_row_panels()
    app = _DeadEndNavigationApp(agents, focused_key="alpha")
    app.current_idx = 1

    app._navigate_agents_panel(direction)

    assert app._panel_group.focused_idx == expected_panel_idx
    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == app._panel_group.panel_keys[expected_panel_idx]
    assert app.current_idx == expected_agent_idx
    assert app._panel_selection_memory["alpha"] == ("agent", 1)
    assert app.armed_departures == [agents[1]]


@pytest.mark.parametrize(
    ("focused_key", "current_idx", "direction", "expected_key"),
    [
        (None, 0, -1, "beta"),
        ("beta", 2, 1, None),
    ],
)
def test_lone_row_panel_escape_wraps(
    focused_key: str | None,
    current_idx: int,
    direction: int,
    expected_key: str | None,
) -> None:
    app = _DeadEndNavigationApp(_single_row_panels(), focused_key=focused_key)
    app.current_idx = current_idx

    app._navigate_agents_panel(direction)

    assert app._panel_group.focused_key == expected_key
    focus = app._resolve_focused_panel()
    assert focus is not None and focus.panel_key == expected_key


def test_lone_row_escape_can_select_collapsed_neighbor() -> None:
    app = _DeadEndNavigationApp(_single_row_panels(), focused_key="alpha")
    app.current_idx = 1
    app._collapsed_panel_keys.add("beta")
    app._sync_panel_group()

    app._navigate_agents_panel(1)

    assert app._panel_group.focused_key == "beta"
    focus = app._resolve_focused_panel()
    assert focus is not None
    assert focus.panel_key == "beta"
    assert focus.collapsed is True


def test_lone_collapsed_grouping_banner_escapes_without_arming_agent() -> None:
    agents = [
        make_agent(name="source-one", project="source", tribe=None),
        make_agent(name="source-two", project="source", tribe=None),
        make_agent(name="alpha", project="alpha", tribe="alpha"),
    ]
    app = _DeadEndNavigationApp(agents, focused_key=None)
    banner = ("source",)
    app._group_fold_registry.for_panel(None).collapse(banner)
    app._current_group_key = banner

    assert app._panel_navigation_stops() == [("banner", banner)]

    app._navigate_agents_panel(1)

    assert app._panel_group.focused_key == "alpha"
    assert app._resolve_focused_panel() is not None
    assert app._panel_selection_memory[None] == ("banner", banner)
    assert app.armed_departures == []


def test_multi_row_panel_keeps_intra_panel_navigation() -> None:
    agents = [
        make_agent(name="default", project="default", tribe=None),
        make_agent(name="alpha-one", project="alpha-one", tribe="alpha"),
        make_agent(name="alpha-two", project="alpha-two", tribe="alpha"),
        make_agent(name="beta", project="beta", tribe="beta"),
    ]
    app = _DeadEndNavigationApp(agents, focused_key="alpha")
    app.current_idx = 1
    focused_idx = app._panel_group.focused_idx

    app._navigate_agents_panel(1)

    assert app._panel_group.focused_idx == focused_idx
    assert app._resolve_focused_panel() is None
    assert app.current_idx == 2


def test_lone_row_in_only_panel_remains_row_focused() -> None:
    app = _DeadEndNavigationApp([make_agent(name="only", project="only", tribe=None)])
    before = (app._panel_group.focused_idx, app.current_idx)

    app._navigate_agents_panel(1)

    assert (app._panel_group.focused_idx, app.current_idx) == before
    assert app._resolve_focused_panel() is None


def test_lone_row_in_merged_layout_remains_row_focused() -> None:
    app = _DeadEndNavigationApp(
        [make_agent(name="only", project="only", tribe="alpha")],
        merged=True,
    )
    before = (app._panel_group.focused_idx, app.current_idx)

    app._navigate_agents_panel(1)

    assert (app._panel_group.focused_idx, app.current_idx) == before
    assert app._resolve_focused_panel() is None


def test_existing_whole_panel_focus_hops_exactly_once() -> None:
    app = _DeadEndNavigationApp(_single_row_panels(), focused_key="alpha")
    app.current_idx = 1
    assert app._activate_focused_panel() is True

    app._navigate_agents_panel(1)

    assert app._panel_group.focused_idx == 2
    focus = app._resolve_focused_panel()
    assert focus is not None and focus.panel_key == "beta"


def test_artifact_file_viewer_guard_blocks_dead_end_escape_once() -> None:
    app = _DeadEndNavigationApp(_single_row_panels(), focused_key="alpha")
    app.current_idx = 1
    focused_idx = app._panel_group.focused_idx
    app.artifact_file_viewer_guard_active = True

    app._navigate_agents_panel(1)

    assert app._panel_group.focused_idx == focused_idx
    assert app._resolve_focused_panel() is None
    assert app.notifications == [ARTIFACT_FILE_VIEWER_NAV_MESSAGE]


def test_zero_stop_panel_surfaces_artifact_file_viewer_guard() -> None:
    app = _ZeroStopNavigationApp(_single_row_panels(), focused_key="alpha")
    focused_idx = app._panel_group.focused_idx
    app.artifact_file_viewer_guard_active = True

    app._navigate_agents_panel(1)

    assert app._panel_group.focused_idx == focused_idx
    assert app._resolve_focused_panel() is None
    assert app.notifications == [ARTIFACT_FILE_VIEWER_NAV_MESSAGE]


def test_zero_stop_panel_selects_adjacent_whole_panel() -> None:
    app = _ZeroStopNavigationApp(_single_row_panels(), focused_key="alpha")

    app._navigate_agents_panel(1)

    assert app._panel_group.focused_key == "beta"
    focus = app._resolve_focused_panel()
    assert focus is not None and focus.panel_key == "beta"

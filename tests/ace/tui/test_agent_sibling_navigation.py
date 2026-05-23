"""Tests for Agents-tab ``~`` sibling navigation."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.navigation._tree import TreeNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.modals import AgentSiblingModal


class _Debouncer:
    def __init__(self) -> None:
        self.scheduled = 0

    def schedule(self, _callback: Any) -> None:
        self.scheduled += 1


class _SiblingApp(TreeNavigationMixin, AgentDisplayMixin):
    """Small harness for the shared ``~`` action and Agents sibling helpers."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        current_idx: int = 0,
        focused_key: str | None = None,
        collapsed: list[tuple[str, ...]] | None = None,
    ) -> None:
        self.current_tab = "agents"
        self.changespecs = []
        self.current_idx = current_idx
        self.current_attempt_number: int | None = 7
        self._agents = agents
        self._agent_panels_grouped = False
        self._panel_group = AgentPanelGroup.from_agents(agents, focused_key)
        self._group_fold_registry = AgentGroupFoldRegistry()
        for key in collapsed or []:
            self._group_fold_registry.collapse(key)
        self._grouping_mode = GroupingMode.STANDARD
        self._current_group_key: tuple[str, ...] | None = None
        self._panel_keys_cache = None
        self._agent_panel_index_cache = None
        self._agent_sibling_index_cache = None
        self._agent_info_metrics_cache = None
        self._marked_agents = set()
        self._unread_completed_agent_ids = set()
        self._manual_unread_agent_ids = set()
        self._fold_counts = {}
        self._agent_search_query = ""
        self._countdown_remaining = 0
        self.refresh_interval = 10
        self.artifact_viewer_guard_active = False
        self.notify = MagicMock()
        self.armed_departures: list[Agent] = []
        self.acknowledged: list[Agent] = []
        self.highlight_refreshes = 0
        self.focused_panel_refreshes: list[int | None] = []
        self.info_updates = 0
        self.detail_updates = 0
        self._agent_detail_debouncer = _Debouncer()
        self.pushed_screens: list[Any] = []
        self.pushed_callbacks: list[Any] = []

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _guard_agent_navigation_for_artifact_viewer(self) -> bool:
        if not self.artifact_viewer_guard_active:
            return False
        self.notify(
            "Close the artifact viewer before switching agents",
            severity="warning",
        )
        return True

    def _arm_manual_unread_after_departure(self, agent: Agent | None) -> None:
        if agent is not None:
            self.armed_departures.append(agent)

    def _acknowledge_agent_unread(self, agent: Agent) -> bool:
        self.acknowledged.append(agent)
        return True

    def _refresh_panel_highlights(self) -> None:
        self.highlight_refreshes += 1

    def _refresh_focused_agent_panel(self, *, old_focused_idx: int | None) -> None:
        self.focused_panel_refreshes.append(old_focused_idx)

    def _update_agents_info_panel(self) -> None:
        self.info_updates += 1

    def _apply_agent_detail_immediate(self) -> None:
        self.detail_updates += 1

    def _fire_debounced_detail_update(self) -> None:
        return

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.pushed_screens.append(screen)
        self.pushed_callbacks.append(callback)


class _ChangespecSiblingApp(TreeNavigationMixin):
    def __init__(self) -> None:
        self.current_tab = "changespecs"
        self.changespecs = [object()]
        self._sibling_keys = {"~": "target"}
        self.navigated: list[tuple[str, bool, bool]] = []

    def _navigate_to_changespec(
        self,
        target_name: str,
        is_ancestor: bool,
        is_sibling: bool = False,
    ) -> None:
        self.navigated.append((target_name, is_ancestor, is_sibling))


def _agent(
    name: str,
    *,
    tag: str | None = None,
    status: str = "RUNNING",
    cl: str = "demo",
    project: str = "proj",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.sase",
        status=status,
        start_time=datetime(2026, 5, 23, 12, 0, 0),
        raw_suffix=name,
        agent_name=name,
        tag=tag,
    )


def test_changespec_sibling_navigation_still_direct_jumps() -> None:
    app = _ChangespecSiblingApp()

    app.action_start_sibling_mode()

    assert app.navigated == [("target", False, True)]


def test_agent_sibling_navigation_noops_without_visible_sibling() -> None:
    app = _SiblingApp([_agent("foo.plan"), _agent("bar.plan")])

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app.acknowledged == []
    assert app.highlight_refreshes == 0


def test_agent_sibling_navigation_direct_jumps_to_single_sibling() -> None:
    agents = [_agent("foo.plan"), _agent("foo.code")]
    app = _SiblingApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app.armed_departures == [agents[0]]
    assert app.acknowledged == [agents[1]]
    assert app.highlight_refreshes == 1
    assert app.info_updates == 1
    assert app.detail_updates == 1
    assert app._agent_detail_debouncer.scheduled == 1


def test_agent_sibling_navigation_direct_jumps_from_descendant_to_root() -> None:
    agents = [_agent("foo.bar"), _agent("foo")]
    app = _SiblingApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.armed_departures == [agents[0]]
    assert app.acknowledged == [agents[1]]


def test_agent_sibling_navigation_direct_jumps_from_root_to_descendant() -> None:
    agents = [_agent("foo"), _agent("foo.bar")]
    app = _SiblingApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.armed_departures == [agents[0]]
    assert app.acknowledged == [agents[1]]


def test_agent_sibling_navigation_opens_modal_for_multiple_siblings() -> None:
    agents = [_agent("foo.plan"), _agent("foo"), _agent("foo.review")]
    app = _SiblingApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentSiblingModal)
    assert [choice.global_idx for choice in modal._choices] == [1, 2]
    assert [choice.agent_name for choice in modal._choices] == ["foo", "foo.review"]
    assert modal._family_label == "foo family"

    app.pushed_callbacks[0](2)

    assert app.current_idx == 2
    assert app.acknowledged == [agents[2]]


def test_agent_sibling_navigation_switches_focused_panel() -> None:
    agents = [
        _agent("foo.plan"),
        _agent("foo.code", tag="review"),
    ]
    app = _SiblingApp(agents)
    assert app._panel_group.panel_keys == [None, "review"]

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert app.focused_panel_refreshes == [0]
    assert app.highlight_refreshes == 0


def test_agent_sibling_navigation_excludes_collapsed_hidden_rows() -> None:
    agents = [
        _agent("foo.code"),
        _agent("foo.plan"),
        _agent("foo.plan.review"),
    ]
    app = _SiblingApp(
        agents,
        current_idx=0,
        collapsed=[("proj", "demo", "foo", "foo.plan")],
    )

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app.acknowledged == []


def test_agent_sibling_navigation_guard_blocks_row_change() -> None:
    agents = [_agent("foo.plan"), _agent("foo.code")]
    app = _SiblingApp(agents)
    app.artifact_viewer_guard_active = True

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app.acknowledged == []
    app.notify.assert_called_once_with(
        "Close the artifact viewer before switching agents",
        severity="warning",
    )

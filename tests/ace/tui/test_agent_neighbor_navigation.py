"""Tests for Agents-tab ``~`` neighbor navigation (dotted-name hoods)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.actions.navigation._tree import TreeNavigationMixin
from sase.ace.tui.modals import AgentNeighborModal
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup


class _Debouncer:
    def __init__(self) -> None:
        self.scheduled = 0

    def schedule(self, _callback: Any) -> None:
        self.scheduled += 1


class _NeighborApp(TreeNavigationMixin, AdvancedNavigationMixin, AgentDisplayMixin):
    """Small harness for the shared ``~`` action and Agents neighbor helpers."""

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
        self._agent_neighbor_index_cache = None
        self._dismiss_revive_epoch = 0
        self._agent_info_metrics_cache = None
        self._dismissed_agents = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_banner: dict[str, Any] = {}
        self._entry_jump_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_hint_to_changespec_banner: dict[str, tuple[str, ...]] = {}
        self._entry_jump_changespec_banner_to_hint: dict[tuple[str, ...], str] = {}
        self._entry_jump_index_stack: dict[str, list[int]] = {}
        self._entry_jump_agents_anchor_stack: list[Any] = []
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
        self.display_refreshes: list[dict[str, Any]] = []
        self.current_tab_refreshes = 0
        self.jump_footer_updates = 0
        self.revived_agents: list[Agent] = []
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

    def _refresh_agents_display(self, **kwargs: Any) -> None:
        self.display_refreshes.append(kwargs)

    def _refresh_current_tab(self) -> None:
        self.current_tab_refreshes += 1

    def _update_jump_footer(self) -> None:
        self.jump_footer_updates += 1

    def _refresh_focused_agent_panel(self, *, old_focused_idx: int | None) -> None:
        self.focused_panel_refreshes.append(old_focused_idx)

    def _update_agents_info_panel(self) -> None:
        self.info_updates += 1

    def _apply_agent_detail_immediate(self) -> None:
        self.detail_updates += 1

    def _fire_debounced_detail_update(self) -> None:
        return

    def _do_revive_agent(self, agent: Agent) -> None:
        self.revived_agents.append(agent)

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


def test_agent_neighbor_navigation_noops_without_visible_neighbor() -> None:
    app = _NeighborApp([_agent("foo.plan"), _agent("bar.plan")])
    app._entry_jump_agents_anchor_stack = [("agent", 1, None)]

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app.acknowledged == []
    assert app.highlight_refreshes == 0
    assert app._entry_jump_agents_anchor_stack == [("agent", 1, None)]


def test_agent_neighbor_navigation_direct_jumps_to_single_neighbor() -> None:
    agents = [_agent("foo.plan"), _agent("foo.code")]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app.armed_departures == [agents[0]]
    assert app.acknowledged == [agents[1]]
    assert app.highlight_refreshes == 1
    assert app.info_updates == 1
    assert app.detail_updates == 1
    assert app._agent_detail_debouncer.scheduled == 1


def test_agent_neighbor_navigation_back_jump_restores_origin() -> None:
    agents = [_agent("foo.plan"), _agent("foo.code")]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()
    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("apostrophe")

    assert handled is True
    assert app.current_idx == 0
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 1


def test_agent_neighbor_navigation_fast_back_jump_restores_origin_without_hints() -> (
    None
):
    agents = [_agent("foo.plan"), _agent("foo.code")]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()
    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_agent_neighbor_navigation_opens_modal_for_dotless_root_descendants() -> None:
    agents = [_agent("foo"), _agent("foo.bar"), _agent("foo.baz")]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [choice.group for choice in modal._choices] == [
        "descendant",
        "descendant",
    ]
    assert [choice.agent_name for choice in modal._choices] == ["foo.bar", "foo.baz"]


def test_agent_neighbor_navigation_fast_jumps_to_single_visible_descendant() -> None:
    agents = [_agent("foo.bar"), _agent("foo.bar.baz")]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.pushed_screens == []
    assert app.acknowledged == [agents[1]]


def test_agent_neighbor_navigation_fast_jumps_to_single_visible_ancestor() -> None:
    agents = [
        _agent("foo", status="DONE"),
        _agent("foo.bar", status="RUNNING"),
    ]
    app = _NeighborApp(agents, current_idx=1)

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app._entry_jump_agents_anchor_stack == [("agent", 1, None)]
    assert app.armed_departures == [agents[1]]
    assert app.acknowledged == [agents[0]]


def test_agent_neighbor_navigation_opens_modal_with_ancestors_first() -> None:
    agents = [
        _agent("foo"),
        _agent("foo.bar"),
        _agent("foo.bar.baz"),
        _agent("foo.qux"),
    ]
    app = _NeighborApp(agents, current_idx=1)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [choice.group for choice in modal._choices] == [
        "ancestor",
        "descendant",
        "neighbor",
    ]
    assert [choice.global_idx for choice in modal._choices] == [0, 2, 3]
    assert modal._title_text() == (
        "Neighbors of foo.bar  [1 ancestor - 1 descendant - 1 neighbor]"
    )
    assert [
        str(option.id) for option in modal._create_options() if option.disabled
    ] == [
        "header-ancestors",
        "header-descendants",
        "header-neighbors",
    ]

    app.pushed_callbacks[0](0)

    assert app.current_idx == 0
    assert app.acknowledged == [agents[0]]


def test_selected_agent_neighbor_count_includes_ancestors() -> None:
    agents = [_agent("foo"), _agent("foo.bar")]
    app = _NeighborApp(agents, current_idx=1)

    assert app._selected_agent_neighbor_count(agents[1]) == 1


def test_agent_neighbor_navigation_jumps_within_a_sub_hood() -> None:
    agents = [_agent("foo.bar.baz"), _agent("foo.bar.qux")]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.armed_departures == [agents[0]]
    assert app.acknowledged == [agents[1]]


def test_agent_neighbor_navigation_opens_modal_for_multiple_neighbors() -> None:
    agents = [_agent("foo.plan"), _agent("foo.code"), _agent("foo.review")]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == []
    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [choice.global_idx for choice in modal._choices] == [1, 2]
    assert [choice.agent_name for choice in modal._choices] == [
        "foo.code",
        "foo.review",
    ]
    assert modal._hood_label == "foo"

    app.pushed_callbacks[0](None)

    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == []
    assert app.acknowledged == []

    app.pushed_callbacks[0](1)

    assert app.current_idx == 2
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert app.acknowledged == [agents[2]]


def test_agent_neighbor_navigation_selecting_visible_descendant_jumps() -> None:
    agents = [_agent("foo"), _agent("foo.bar"), _agent("foo.baz")]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()

    app.pushed_callbacks[0](0)

    assert app.current_idx == 1
    assert app.acknowledged == [agents[1]]


def test_agent_neighbor_navigation_selecting_dismissed_descendant_revives() -> None:
    visible = [_agent("foo.bar")]
    dismissed = _agent("foo.bar.dismissed", status="DONE")
    app = _NeighborApp(visible)
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    app._dismiss_revive_epoch += 1

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [(choice.agent_name, choice.dismissed) for choice in modal._choices] == [
        ("foo.bar.dismissed", True)
    ]

    app.pushed_callbacks[0](0)

    assert app.revived_agents == [dismissed]
    assert app.current_idx == 0


def test_agent_neighbor_navigation_switches_focused_panel() -> None:
    agents = [
        _agent("foo.plan"),
        _agent("foo.code", tag="review"),
    ]
    app = _NeighborApp(agents)
    assert app._panel_group.panel_keys == [None, "review"]

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert app.focused_panel_refreshes == [0]
    assert app.highlight_refreshes == 0


def test_agent_neighbor_navigation_excludes_collapsed_hidden_rows() -> None:
    agents = [
        _agent("foo.code"),
        _agent("foo.plan"),
        _agent("foo.plan.review"),
    ]
    app = _NeighborApp(
        agents,
        current_idx=0,
        collapsed=[("proj", "demo", "foo", "foo.plan")],
    )

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app.acknowledged == []


def test_agent_neighbor_navigation_guard_blocks_row_change() -> None:
    agents = [_agent("foo.plan"), _agent("foo.code")]
    app = _NeighborApp(agents)
    app.artifact_viewer_guard_active = True
    app._entry_jump_agents_anchor_stack = [("agent", 1, None)]

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app.acknowledged == []
    assert app._entry_jump_agents_anchor_stack == [("agent", 1, None)]
    app.notify.assert_called_once_with(
        "Close the artifact viewer before switching agents",
        severity="warning",
    )

"""Tests for Agents-tab ``~`` neighbor navigation (dotted-name hoods)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.actions.navigation._tree import TreeNavigationMixin
from sase.ace.tui.modals import AgentNeighborModal
from sase.ace.tui.models import filter_agents_by_fold_state
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager


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
        collapsed_panel_keys: set[str | None] | None = None,
    ) -> None:
        self.current_tab = "agents"
        self.changespecs = []
        self.current_idx = current_idx
        self.current_attempt_number: int | None = 7
        self._agents_with_children = list(agents)
        self._agents = list(agents)
        self._fold_manager = FoldStateManager()
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._agent_panels_grouped = False
        self._collapsed_panel_keys = set(collapsed_panel_keys or ())
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            focused_key,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
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
        self._entry_jump_agents_forward_anchor_stack: list[Any] = []
        self._marked_agents = set()
        self._unread_completed_agent_ids = set()
        self._manual_unread_agent_ids = set()
        self._fold_counts = {}
        self._agent_search_query = ""
        self._countdown_remaining = 0
        self.refresh_interval = 10
        self.artifact_file_viewer_guard_active = False
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
        self.refilter_calls = 0
        self.group_fold_changes: list[tuple[tuple[str, ...], bool]] = []
        self.panel_fold_changes: list[tuple[str | None, bool]] = []
        self._agent_detail_debouncer = _Debouncer()
        self.pushed_screens: list[Any] = []
        self.pushed_callbacks: list[Any] = []

    def _get_selected_agent(self) -> Agent | None:
        if self._agents and 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        if not self.artifact_file_viewer_guard_active:
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
        if kwargs.get("list_changed"):
            self._sync_panel_group()

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

    def _refilter_agents(self, **_kwargs: Any) -> None:
        self.refilter_calls += 1
        focused_key = self._panel_group.focused_key
        self._agents, self._fold_counts = filter_agents_by_fold_state(
            self._agents_with_children,
            self._fold_manager,
        )
        self._invalidate_agent_panel_cache()
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )

    def _expand_agent_panel(self, panel_key: str | None) -> bool:
        if panel_key not in self._collapsed_panel_keys:
            return False
        self._collapsed_panel_keys.remove(panel_key)
        self._invalidate_agent_panel_cache()
        self._persist_panel_fold_change(panel_key, collapsed=False)
        return True

    def _persist_group_fold_change(
        self,
        group_key: tuple[str, ...],
        *,
        collapsed: bool,
        panel_key: str | None = None,
    ) -> None:
        del panel_key
        self.group_fold_changes.append((group_key, collapsed))

    def _persist_panel_fold_change(
        self,
        panel_key: str | None,
        *,
        collapsed: bool,
    ) -> None:
        self.panel_fold_changes.append((panel_key, collapsed))

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
    assert app.refilter_calls == 0
    assert app.display_refreshes == []


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
        "header-neighbors-0",
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
    assert [choice.hood for choice in modal._choices] == ["foo", "foo"]

    app.pushed_callbacks[0](None)

    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == []
    assert app.acknowledged == []

    app.pushed_callbacks[0](1)

    assert app.current_idx == 2
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert app.acknowledged == [agents[2]]


def test_agent_neighbor_navigation_groups_nephews_and_cousins() -> None:
    agents = [
        _agent("A.B.C"),
        _agent("a.b.d.e"),
        _agent("a.z.1"),
        _agent("unrelated.agent"),
    ]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()

    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [choice.agent_name for choice in modal._choices] == [
        "a.b.d.e",
        "a.z.1",
    ]
    assert [choice.hood for choice in modal._choices] == ["A.B", "A"]
    assert [
        option.prompt.plain for option in modal._create_options() if option.disabled
    ] == [
        "-- Neighbors - A.B hood (1) --------------------",
        "-- Neighbors - A hood (1) --------------------",
    ]


def test_agent_neighbor_navigation_direct_jumps_to_single_nephew() -> None:
    agents = [_agent("foo.bar"), _agent("foo.baz.qux")]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.pushed_screens == []
    assert app.acknowledged == [agents[1]]


def test_agent_neighbor_navigation_top_level_family_mates_are_unrelated() -> None:
    app = _NeighborApp([_agent("fam--plan"), _agent("fam--fix")])

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app.acknowledged == []


def test_agent_neighbor_navigation_direct_jumps_down_family_chain() -> None:
    agents = [_agent("fam--plan"), _agent("fam--plan--check")]
    app = _NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.pushed_screens == []
    assert app.acknowledged == [agents[1]]


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


def test_agent_neighbor_navigation_revives_dismissed_family_descendant() -> None:
    visible = [_agent("fam--plan")]
    dismissed = _agent("fam--plan--dismissed", status="DONE")
    app = _NeighborApp(visible)
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    app._dismiss_revive_epoch += 1

    app.action_start_sibling_mode()

    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [(choice.agent_name, choice.dismissed) for choice in modal._choices] == [
        ("fam--plan--dismissed", True)
    ]

    app.pushed_callbacks[0](0)

    assert app.revived_agents == [dismissed]


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
    app.artifact_file_viewer_guard_active = True
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


def test_agent_neighbor_navigation_reveals_collapsed_target_panel_once() -> None:
    origin = _agent("foo.plan")
    target = _agent("foo.code", tag="alpha", status="DONE")
    unrelated = _agent("unrelated.agent", tag="zeta")
    app = _NeighborApp(
        [origin, target, unrelated],
        collapsed_panel_keys={"alpha"},
    )
    assert app._panel_group.panel_keys == [None, "zeta", "alpha"]

    app.action_start_sibling_mode()

    assert app._agents[app.current_idx].identity == target.identity
    assert app._panel_group.panel_keys == [None, "alpha", "zeta"]
    assert app._panel_group.focused_key == "alpha"
    assert "alpha" not in app._collapsed_panel_keys
    assert app.panel_fold_changes == [("alpha", False)]
    assert app.display_refreshes == [{"list_changed": True, "defer_detail": True}]
    assert app.refilter_calls == 0
    assert app.armed_departures == [origin]
    assert app.acknowledged == [target]
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]

    assert app._restore_agents_jump_anchor() is True
    assert app._agents[app.current_idx].identity == origin.identity
    assert app._panel_group.focused_key is None
    assert "alpha" not in app._collapsed_panel_keys


def test_neighbor_reveal_does_not_retry_internal_display_type_error() -> None:
    origin = _agent("foo.plan")
    target = _agent("foo.code", tag="alpha")
    app = _NeighborApp(
        [origin, target],
        collapsed_panel_keys={"alpha"},
    )
    calls: list[dict[str, object]] = []

    def fail_refresh(**kwargs: object) -> None:
        calls.append(dict(kwargs))
        raise TypeError("internal display failure")

    app._refresh_agents_display = fail_refresh  # type: ignore[method-assign]

    with pytest.raises(TypeError, match="internal display failure"):
        app.action_start_sibling_mode()

    assert calls == [{"list_changed": True, "defer_detail": True}]


def test_agent_neighbor_modal_resolves_stale_numeric_index_by_identity() -> None:
    origin = _agent("foo.plan")
    target = _agent("foo.code", tag="alpha")
    other = _agent("foo.review", tag="zeta")
    app = _NeighborApp(
        [origin, target, other],
        collapsed_panel_keys={"alpha"},
    )

    app.action_start_sibling_mode()
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    target_choice_idx = next(
        idx
        for idx, choice in enumerate(modal._choices)
        if choice.agent_name == target.agent_name
    )
    assert modal._choices[target_choice_idx].global_idx == 1

    # The selected identity survives, but the old index now names the origin.
    app._agents = [other, origin, target]
    app._agents_with_children = list(app._agents)
    app.current_idx = 1
    app._invalidate_agent_panel_cache()
    app._panel_group = AgentPanelGroup.from_agents(
        app._agents,
        focused_key=None,
        collapsed_panel_keys=app._collapsed_panel_keys,
    )
    assert app._agents[1].identity == origin.identity

    app.pushed_callbacks[0](target_choice_idx)

    assert app._agents[app.current_idx].identity == target.identity
    assert app.acknowledged == [target]
    assert app.armed_departures == [origin]
    assert app._panel_group.focused_key == "alpha"
    assert app.panel_fold_changes == [("alpha", False)]


def test_agent_neighbor_modal_filtered_target_fails_without_mutation() -> None:
    origin = _agent("foo.plan")
    target = _agent("foo.code", tag="alpha")
    other = _agent("foo.review", tag="zeta")
    app = _NeighborApp(
        [origin, target, other],
        collapsed_panel_keys={"alpha"},
    )

    app.action_start_sibling_mode()
    modal = app.pushed_screens[0]
    target_choice_idx = next(
        idx
        for idx, choice in enumerate(modal._choices)
        if choice.agent_name == target.agent_name
    )
    app._agents = [origin, other]
    app.current_idx = 0
    app._invalidate_agent_panel_cache()
    app._panel_group = AgentPanelGroup.from_agents(
        app._agents,
        focused_key=None,
        collapsed_panel_keys=app._collapsed_panel_keys,
    )

    app.pushed_callbacks[0](target_choice_idx)

    assert app.current_idx == 0
    assert app._agents[app.current_idx].identity == origin.identity
    assert app._collapsed_panel_keys == {"alpha"}
    assert app.panel_fold_changes == []
    assert app.group_fold_changes == []
    assert app.display_refreshes == []
    assert app.armed_departures == []
    assert app.acknowledged == []
    assert app._entry_jump_agents_anchor_stack == []


def test_agent_neighbor_reveals_only_target_tree_ancestry() -> None:
    origin = _agent("foo.plan")
    target_parent = _agent("target-container")
    target_parent.agent_clan = "target-clan"
    target = _agent("foo.code")
    target.parent_timestamp = target_parent.raw_suffix

    other_parent = _agent("other-container")
    other_parent.agent_clan = "other-clan"
    other_child = _agent("unrelated.child")
    other_child.parent_timestamp = other_parent.raw_suffix
    complete = project_clan_tree(
        [other_parent, other_child, origin, target_parent, target]
    )
    origin_idx = next(
        idx for idx, agent in enumerate(complete) if agent.identity == origin.identity
    )
    app = _NeighborApp(complete, current_idx=origin_idx)
    target_clan = next(
        agent
        for agent in complete
        if agent.is_clan_container and agent.agent_clan == "target-clan"
    )
    other_clan = next(
        agent
        for agent in complete
        if agent.is_clan_container and agent.agent_clan == "other-clan"
    )
    target_clan_key = agent_fold_key(target_clan)
    other_clan_key = agent_fold_key(other_clan)
    assert target_clan_key is not None
    assert other_clan_key is not None

    app.action_start_sibling_mode()

    assert app._agents[app.current_idx].identity == target.identity
    assert app._fold_manager.get(target_clan_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(target_parent.raw_suffix or "") is FoldLevel.EXPANDED
    assert app._fold_manager.get(other_clan_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(other_parent.raw_suffix or "") is FoldLevel.COLLAPSED
    assert app._fold_manager.get(target.raw_suffix or "") is FoldLevel.COLLAPSED
    assert app.refilter_calls == 1
    assert app.display_refreshes == [{"list_changed": True, "defer_detail": True}]

    assert app._restore_agents_jump_anchor() is True
    assert app._agents[app.current_idx].identity == origin.identity
    assert app._fold_manager.get(target_clan_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(target_parent.raw_suffix or "") is FoldLevel.EXPANDED

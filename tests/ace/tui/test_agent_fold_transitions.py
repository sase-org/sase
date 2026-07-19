"""Per-group transition tests for the agents-tab fold mixin.

Covers the boundary between the per-group :class:`AgentGroupFoldRegistry`
and the existing per-workflow :class:`FoldStateManager`: ``l`` expands
the focused group (or runs per-workflow expansion when an agent is
focused inside an already-expanded chain); ``h`` collapses structural
agent/family/clan folds, while ``H`` collapses grouping-strategy folds.
Whole-panel behavior is covered separately in ``test_agent_panel_collapse.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager


class _StubApp(AgentFoldingMixin):
    """Minimal harness mounting the fold mixin in isolation."""

    def __init__(self, agents: list[Agent], current_idx: int = 0) -> None:
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents = agents
        self._fold_manager = FoldStateManager()
        _, self._fold_counts = filter_agents_by_fold_state(agents, self._fold_manager)
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._agent_panels_grouped = False
        self._panel_group = AgentPanelGroup.from_agents(agents)
        self._current_group_key: tuple[str, ...] | None = None
        self.refilter_calls = 0
        self.focus_artifact_result = False
        self.focus_artifact_calls = 0
        self._detail = None
        self.footer_refresh_calls = 0
        self.fold_selector_calls = 0

    # The mixin calls these via attribute lookups.
    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        self.refilter_calls += 1

    def _focus_tracked_artifact_file_tmux_pane(self) -> bool:
        self.focus_artifact_calls += 1
        return self.focus_artifact_result

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def query_one(self, selector: str, *_args: object) -> object:
        if selector == "#agent-detail-panel" and self._detail is not None:
            return self._detail
        raise KeyError(selector)

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refresh_calls += 1

    def action_toggle_selected_agent_panels(self) -> None:
        self.fold_selector_calls += 1


class _ToolsDetail:
    def __init__(self, *, visible: bool = True, changed: bool = True) -> None:
        self.visible = visible
        self.changed = changed
        self.actions: list[str] = []

    def is_tools_visible(self) -> bool:
        return self.visible

    def expand_tools_detail(self) -> bool:
        self.actions.append("expand")
        return self.changed

    def collapse_tools_detail(self) -> bool:
        self.actions.append("collapse")
        return self.changed

    def set_tools_detail_level(self, level: object) -> bool:
        self.actions.append(f"set:{int(level)}")
        return self.changed


def _agent(
    *,
    cl_name: str = "demo",
    project: str = "proj",
    agent_name: str | None = None,
    raw_suffix: str | None = None,
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "RUNNING",
    tag: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file=f"/r/{project}/proj.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        tribe=tag,
    )


def test_tools_panel_routes_fold_keys_except_capital_l_to_detail_level() -> None:
    agent = _agent(agent_name="coder.claude")
    detail = _ToolsDetail()
    app = _StubApp([agent], current_idx=0)
    app._detail = detail

    app.action_expand_or_layout()
    app.action_hooks_or_collapse()
    app.action_expand_all_folds()
    app.action_hooks_or_collapse_all()

    assert detail.actions == ["expand", "collapse", "set:0"]
    assert app.fold_selector_calls == 1
    assert app.refilter_calls == 0
    assert app.footer_refresh_calls == 3


def test_tools_panel_detail_clamp_does_not_fall_through_to_folds() -> None:
    agent = _agent(agent_name="coder.claude")
    detail = _ToolsDetail(changed=False)
    app = _StubApp([agent], current_idx=0)
    app._detail = detail

    app.action_expand_or_layout()

    assert detail.actions == ["expand"]
    assert app.refilter_calls == 0
    assert app.footer_refresh_calls == 0


class _OtherTabExpandApp(AgentFoldingMixin):
    def __init__(self, current_tab: Literal["axe", "changespecs"]) -> None:
        self.current_tab = current_tab
        self.axe_expand_calls = 0
        self.changespec_expand_calls = 0
        self.refresh_calls = 0

    def _expand_all_axe_folds(self) -> None:
        self.axe_expand_calls += 1

    def _expand_all_changespec_group_folds(self) -> bool:
        self.changespec_expand_calls += 1
        return True

    def _refresh_display(self) -> None:
        self.refresh_calls += 1


def test_capital_l_still_expands_all_folds_on_other_tabs() -> None:
    axe = _OtherTabExpandApp("axe")
    changespecs = _OtherTabExpandApp("changespecs")

    axe.action_expand_all_folds()
    changespecs.action_expand_all_folds()

    assert axe.axe_expand_calls == 1
    assert axe.refresh_calls == 0
    assert changespecs.changespec_expand_calls == 1
    assert changespecs.refresh_calls == 1


def test_capital_h_on_agent_collapses_only_its_group() -> None:
    """Two projects A + B; pressing ``H`` in A leaves B untouched."""
    a = _agent(cl_name="cl-a", project="projA")
    b = _agent(cl_name="cl-b", project="projB")
    app = _StubApp([a, b], current_idx=0)

    app.action_hooks_or_collapse_all()  # focus is on agent in projA
    assert app._group_fold_registry.is_collapsed(("projA", "cl-a")) is True
    assert app._group_fold_registry.is_collapsed(("projB", "cl-b")) is False
    # Focus snapped onto the now-visible projA banner.
    assert app._current_group_key == ("projA", "cl-a")


def test_capital_h_inside_l1_collapses_l1_then_parent_l0() -> None:
    """Focus inside an L1: first ``H`` collapses L1, second collapses L0."""
    a = _agent(agent_name="coder.claude")
    b = _agent(agent_name="coder.codex")
    app = _StubApp([a, b], current_idx=0)
    l1 = ("proj", "demo", "coder")
    l0 = ("proj", "demo")

    app.action_hooks_or_collapse_all()
    assert app._group_fold_registry.is_collapsed(l1) is True
    assert app._group_fold_registry.is_collapsed(l0) is False
    assert app._current_group_key == l1

    app.action_hooks_or_collapse_all()
    assert app._group_fold_registry.is_collapsed(l0) is True
    assert app._current_group_key == l0


def test_l_on_collapsed_l1_banner_expands_only_that_l1() -> None:
    """`l` while focused on a collapsed L1 expands only that group."""
    a = _agent(agent_name="coder.claude")
    b = _agent(agent_name="coder.codex")
    c = _agent(agent_name="planner.claude")
    d = _agent(agent_name="planner.codex")
    app = _StubApp([a, b, c, d], current_idx=0)
    coder = ("proj", "demo", "coder")
    planner = ("proj", "demo", "planner")
    app._group_fold_registry.collapse(coder)
    app._group_fold_registry.collapse(planner)
    app._current_group_key = coder

    app.action_expand_or_layout()
    assert app._group_fold_registry.is_collapsed(coder) is False
    assert app._group_fold_registry.is_collapsed(planner) is True


def test_l_expands_agent_fold_without_artifact_pane_focus() -> None:
    a = _agent(agent_name="coder.claude")
    app = _StubApp([a], current_idx=0)
    key = ("proj", "demo", "coder")
    app._group_fold_registry.collapse(key)
    app._current_group_key = key
    app.focus_artifact_result = True

    app.action_expand_or_layout()

    assert app.focus_artifact_calls == 0
    assert app._group_fold_registry.is_collapsed(key) is False
    assert app.refilter_calls == 1


def test_l_expands_running_parent_with_family_child() -> None:
    parent = _agent(raw_suffix="parent-ts")
    child = _agent(raw_suffix="child-ts")
    child.parent_timestamp = parent.raw_suffix
    app = _StubApp([parent, child], current_idx=0)

    app.action_expand_or_layout()

    assert app._fold_manager.get("parent-ts") is FoldLevel.EXPANDED
    assert app.refilter_calls == 1


def test_clan_l_is_a_binary_outer_fold_and_second_l_is_clamped() -> None:
    first = _agent(raw_suffix="first")
    first.agent_clan = "research"
    first.agent_clan_generation = "generation"
    second = _agent(raw_suffix="second")
    second.agent_clan = "research"
    second.agent_clan_generation = "generation"
    projected = project_clan_tree([first, second])
    app = _StubApp(projected)
    key = agent_fold_key(projected[0])
    assert key is not None

    app.action_expand_or_layout()
    assert app._fold_manager.get(key) is FoldLevel.EXPANDED
    app.action_expand_or_layout()
    assert app._fold_manager.get(key) is FoldLevel.EXPANDED
    app.action_hooks_or_collapse()
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    assert app.refilter_calls == 2


def test_clan_member_l_l_and_child_member_h_h_are_isolated() -> None:
    workflow = _agent(raw_suffix="workflow", agent_type=AgentType.WORKFLOW)
    workflow.agent_clan = "research"
    workflow.agent_clan_generation = "generation"
    ordinary = _agent(raw_suffix="ordinary", agent_type=AgentType.WORKFLOW)
    ordinary.parent_timestamp = workflow.raw_suffix
    ordinary.parent_workflow = "workflow"
    ordinary.step_type = "agent"
    hidden = _agent(raw_suffix="hidden", agent_type=AgentType.WORKFLOW)
    hidden.parent_timestamp = workflow.raw_suffix
    hidden.parent_workflow = "workflow"
    hidden.step_type = "bash"
    hidden.is_hidden_step = True

    family = _agent(raw_suffix="family")
    family.agent_clan = "research"
    family.agent_clan_generation = "generation"
    followup = _agent(raw_suffix="followup")
    followup.parent_timestamp = family.raw_suffix

    projected = project_clan_tree([workflow, ordinary, hidden, family, followup])
    container, workflow, ordinary, hidden, family, followup = projected
    clan_key = agent_fold_key(container)
    workflow_key = agent_fold_key(workflow)
    family_key = agent_fold_key(family)
    assert clan_key is not None
    assert workflow_key is not None
    assert family_key is not None
    app = _StubApp(projected)

    app.action_expand_or_layout()
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED

    app.current_idx = projected.index(workflow)
    app.action_expand_or_layout()
    assert app._fold_manager.get(workflow_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED

    app.action_expand_or_layout()
    assert app._fold_manager.get(workflow_key) is FoldLevel.FULLY_EXPANDED
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED

    app.current_idx = projected.index(hidden)
    app.action_hooks_or_collapse()
    assert app._fold_manager.get(workflow_key) is FoldLevel.EXPANDED
    assert app.current_idx == projected.index(workflow)

    app.action_hooks_or_collapse()
    assert app._fold_manager.get(workflow_key) is FoldLevel.COLLAPSED
    assert app.current_idx == projected.index(workflow)

    app.action_hooks_or_collapse()
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    assert app.current_idx == projected.index(container)
    assert app._group_fold_registry.collapsed == set()


def test_collapsed_clan_masks_member_state_until_reopened() -> None:
    member = _agent(raw_suffix="member", agent_type=AgentType.WORKFLOW)
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    child = _agent(raw_suffix="child", agent_type=AgentType.WORKFLOW)
    child.parent_timestamp = member.raw_suffix
    child.parent_workflow = "workflow"
    child.step_type = "agent"
    projected = project_clan_tree([member, child])
    container, member, child = projected
    clan_key = agent_fold_key(container)
    member_key = agent_fold_key(member)
    assert clan_key is not None
    assert member_key is not None
    app = _StubApp(projected)

    app.action_expand_or_layout()
    app.current_idx = projected.index(member)
    app.action_expand_or_layout()
    assert app._fold_manager.get(member_key) is FoldLevel.EXPANDED

    app.current_idx = projected.index(container)
    app.action_hooks_or_collapse()
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(member_key) is FoldLevel.EXPANDED

    app.action_expand_or_layout()
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(member_key) is FoldLevel.EXPANDED


def test_per_workflow_h_runs_before_group_collapse() -> None:
    """Per-workflow ``h`` beats group collapse for an expanded workflow."""
    parent = _agent(raw_suffix="ts1", agent_type=AgentType.WORKFLOW)
    app = _StubApp([parent])
    app._fold_counts["ts1"] = (1, 0)
    app._fold_manager.expand("ts1")  # EXPANDED

    app.action_hooks_or_collapse()
    # Workflow collapsed; group registry untouched.
    assert app._fold_manager.get("ts1") == FoldLevel.COLLAPSED
    assert app._group_fold_registry.collapsed == set()


def test_capital_h_then_l_round_trip_clears_group_focus() -> None:
    """After ``H`` snaps to a banner, ``l`` expands and clears its focus."""
    a = _agent(cl_name="cl-a", project="projA")
    app = _StubApp([a], current_idx=0)
    key = ("projA", "cl-a")

    app.action_hooks_or_collapse_all()
    assert app._current_group_key == key
    assert app._group_fold_registry.is_collapsed(key) is True

    app.action_expand_or_layout()
    assert app._group_fold_registry.is_collapsed(key) is False
    # Banner stopped being selectable — focus moved off it.
    assert app._current_group_key is None


def test_equal_status_group_keys_fold_independently_between_panels() -> None:
    untagged = _agent(status="DONE")
    tagged = _agent(status="DONE", tag="research")
    app = _StubApp([untagged, tagged], current_idx=0)
    app._grouping_mode = GroupingMode.BY_STATUS

    app.action_hooks_or_collapse_all()

    split_done = app._group_fold_registry.for_panel(None)
    tagged_done = app._group_fold_registry.for_panel("research")
    assert split_done.is_collapsed(("Done",)) is True
    assert tagged_done.is_collapsed(("Done",)) is False

    app._panel_group.focused_idx = 1
    app.current_idx = 1
    app._current_group_key = None
    app.action_hooks_or_collapse_all()
    assert tagged_done.is_collapsed(("Done",)) is True

    app.action_expand_or_layout()
    assert tagged_done.is_collapsed(("Done",)) is False
    assert split_done.is_collapsed(("Done",)) is True

"""Per-group transition tests for the agents-tab fold mixin.

Covers the boundary between the per-group :class:`AgentGroupFoldRegistry`
and the existing per-workflow :class:`FoldStateManager`: ``l`` expands the
focused group (or a structural fold), ``h`` navigates to a structural/tribe
parent, and ``H`` collapses structural folds before grouping-strategy folds.
Whole-panel behavior is covered separately in ``test_agent_panel_collapse.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.actions.navigation._entry_jump_agents import (
    EntryJumpAgentHistoryMixin,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.agent_tribe_summary import AgentPanelFocus
from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager


class _StubApp(EntryJumpAgentHistoryMixin, AgentFoldingMixin):
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
        self._expanded_panel_focus = False
        self._collapsed_panel_keys: set[str | None] = set()
        self._expanded_panel_keys: set[str | None] = set()
        self._panel_selection_memory: dict[
            str | None, tuple[str, int | tuple[str, ...]]
        ] = {}
        self._entry_jump_agents_anchor_stack = []
        self._entry_jump_agents_forward_anchor_stack = []
        self.current_attempt_number: int | None = None
        self.armed_departures: list[Agent] = []
        self.acknowledged: list[Agent] = []
        self.refilter_calls = 0
        self.focus_artifact_result = False
        self.focus_artifact_calls = 0
        self._detail = None
        self.footer_refresh_calls = 0
        self.fold_selector_calls = 0
        self.panel_focus_refresh_calls = 0

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

    def _panel_keys_per_agent(self) -> list[str | None]:
        from sase.ace.tui.models.agent_panels import panel_key_per_agent

        return panel_key_per_agent(self._agents)

    def _remember_focused_panel_selection(
        self,
        stop: tuple[str, int | tuple[str, ...]] | None = None,
    ) -> None:
        if stop is None:
            stop = (
                ("banner", self._current_group_key)
                if self._current_group_key is not None
                else ("agent", self.current_idx)
            )
        self._panel_selection_memory[self._panel_group.focused_key] = stop

    def _resolve_focused_panel(self) -> AgentPanelFocus | None:
        key = self._panel_group.focused_key
        collapsed = key in self._collapsed_panel_keys
        if not collapsed and not self._expanded_panel_focus:
            return None
        return AgentPanelFocus(key, collapsed)

    def _activate_focused_panel(self) -> bool:
        if (
            self._agent_panels_grouped
            or len(self._panel_group.panel_keys) <= 1
            or self._resolve_focused_panel() is not None
        ):
            return self._resolve_focused_panel() is not None
        self._remember_focused_panel_selection()
        self._expanded_panel_focus = True
        self._current_group_key = None
        self.current_attempt_number = None
        self.panel_focus_refresh_calls += 1
        return True

    def _arm_manual_unread_after_departure(self, agent: Agent | None) -> None:
        if agent is not None:
            self.armed_departures.append(agent)

    def _acknowledge_agent_unread(self, agent: Agent) -> bool:
        self.acknowledged.append(agent)
        return True

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
    tribe: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file=f"/r/{project}/proj.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        tribe=tribe,
    )


def _sequential_family(
    *,
    clan: str | None = None,
    status: str = "RUNNING",
    tribe: str | None = None,
) -> tuple[list[Agent], Agent, Agent]:
    family = _agent(raw_suffix="family", status=status, tribe=tribe)
    family.plan_chain_root = True
    family.agent_family = "family"
    member = _agent(raw_suffix="member", status=status)
    member.parent_timestamp = family.raw_suffix
    member.agent_family = "family"
    member.agent_family_role = "code"
    family.followup_agents.append(member)
    family.runtime_children.append(member)
    if clan is not None:
        family.agent_clan = clan
        family.agent_clan_generation = "generation"
        projected = project_clan_tree([family, member])
    else:
        projected = [family, member]
    return projected, family, member


def test_tools_panel_h_navigates_while_capital_h_compacts_detail() -> None:
    agent = _agent(agent_name="coder.claude", tribe="research")
    other = _agent(agent_name="planner.codex", tribe="ops")
    detail = _ToolsDetail()
    app = _StubApp([agent, other], current_idx=0)
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")
    app._detail = detail

    app.action_expand_or_layout()
    app.action_hooks_or_collapse()
    app.action_expand_all_folds()
    app.action_hooks_or_collapse_all()

    assert detail.actions == ["expand", "set:0"]
    assert app._expanded_panel_focus is True
    assert app._panel_selection_memory["research"] == ("agent", 0)
    assert app.fold_selector_calls == 1
    assert app.refilter_calls == 0
    assert app.footer_refresh_calls == 2


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


def test_capital_h_collapses_family_then_clan_before_group_fold() -> None:
    projected, family, member = _sequential_family(clan="research")
    clan = projected[0]
    app = _StubApp(projected, current_idx=projected.index(member))
    family_key = agent_fold_key(family)
    clan_key = agent_fold_key(clan)
    assert family_key is not None
    assert clan_key is not None
    app._fold_manager.expand(clan_key)
    app._fold_manager.expand(family_key)

    app.action_hooks_or_collapse_all()

    assert app.current_idx == projected.index(family)
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
    assert app._group_fold_registry.snapshot() == ()

    app.action_hooks_or_collapse_all()

    assert app.current_idx == projected.index(clan)
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    assert app._group_fold_registry.snapshot() == ()

    app.action_hooks_or_collapse_all()

    assert app._current_group_key is not None
    assert app._group_fold_registry.snapshot()


def test_h_walks_member_family_clan_tribe_without_changing_folds() -> None:
    projected, family, member = _sequential_family(
        clan="research",
        tribe="research",
    )
    clan = projected[0]
    projected.append(_agent(raw_suffix="ops", tribe="ops"))
    app = _StubApp(projected, current_idx=projected.index(member))
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")
    family_key = agent_fold_key(family)
    clan_key = agent_fold_key(clan)
    assert family_key is not None
    assert clan_key is not None
    app._fold_manager.expand(clan_key)
    app._fold_manager.expand(family_key)
    tree_folds_before = app._fold_manager.snapshot()
    group_folds_before = app._group_fold_registry.snapshot()
    panel_folds_before = (
        set(app._collapsed_panel_keys),
        set(app._expanded_panel_keys),
    )

    app.action_hooks_or_collapse()
    assert app.current_idx == projected.index(family)
    app.action_hooks_or_collapse()
    assert app.current_idx == projected.index(clan)
    app.action_hooks_or_collapse()

    assert app._expanded_panel_focus is True
    assert app._panel_selection_memory["research"] == (
        "agent",
        projected.index(clan),
    )
    assert app._fold_manager.snapshot() == tree_folds_before
    assert app._group_fold_registry.snapshot() == group_folds_before
    assert (
        app._collapsed_panel_keys,
        app._expanded_panel_keys,
    ) == panel_folds_before
    assert app.refilter_calls == 0


def test_h_parent_navigation_preserves_selection_bookkeeping_and_history() -> None:
    projected, family, member = _sequential_family(clan="research")
    app = _StubApp(projected, current_idx=projected.index(member))
    app.current_attempt_number = 3
    app._current_group_key = None

    app.action_hooks_or_collapse()

    family_idx = projected.index(family)
    member_idx = projected.index(member)
    assert app.current_idx == family_idx
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app._panel_selection_memory[None] == ("agent", family_idx)
    assert app.armed_departures == [member]
    assert app.acknowledged == [family]

    assert app._restore_agents_jump_anchor() is True
    assert app.current_idx == member_idx

    forward = app._entry_jump_agents_forward_stack()
    family_anchor = app._pop_agents_jump_anchor(forward)
    assert family_anchor == ("agent", family_idx, None)
    current = app._current_agents_jump_anchor()
    assert current is not None
    app._push_agents_jump_anchor(app._entry_jump_agents_anchor_stack, current)
    app._restore_agents_jump_anchor_value(family_anchor)
    assert app.current_idx == family_idx


def test_h_parent_ladder_is_grouping_mode_independent() -> None:
    projected, family, member = _sequential_family(
        clan="research",
        status="RUNNING",
    )
    clan = projected[0]
    app = _StubApp(projected, current_idx=projected.index(member))
    app._grouping_mode = GroupingMode.BY_STATUS

    app.action_hooks_or_collapse()
    assert app.current_idx == projected.index(family)
    app.action_hooks_or_collapse()
    assert app.current_idx == projected.index(clan)
    assert app._group_fold_registry.snapshot() == ()


def test_h_standalone_family_member_then_top_level_family_selects_tribe() -> None:
    agents, family, member = _sequential_family(tribe="research")
    agents.append(_agent(raw_suffix="ops", tribe="ops"))
    app = _StubApp(agents, current_idx=agents.index(member))
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")

    app.action_hooks_or_collapse()
    assert app.current_idx == agents.index(family)
    assert app._group_fold_registry.snapshot() == ()

    app.action_hooks_or_collapse()
    assert app._expanded_panel_focus is True
    assert app._group_fold_registry.snapshot() == ()


def test_h_accepts_only_real_agent_family_children() -> None:
    family = _agent(raw_suffix="family", agent_type=AgentType.WORKFLOW)
    family.plan_chain_root = True
    family.agent_family = "family"
    continuation = _agent(raw_suffix="continuation")
    continuation.parent_timestamp = family.raw_suffix
    continuation.agent_family = "family"
    continuation.agent_family_role = "code"
    family.followup_agents.append(continuation)
    family.runtime_children.append(continuation)

    agent_step = _agent(raw_suffix="agent-step", agent_type=AgentType.WORKFLOW)
    agent_step.parent_timestamp = family.raw_suffix
    agent_step.parent_workflow = "workflow"
    agent_step.step_type = "agent"
    bash_step = _agent(raw_suffix="bash-step", agent_type=AgentType.WORKFLOW)
    bash_step.parent_timestamp = family.raw_suffix
    bash_step.parent_workflow = "workflow"
    bash_step.step_type = "bash"
    bash_step.is_hidden_step = True
    agents = [family, agent_step, continuation, bash_step]

    app = _StubApp(agents, current_idx=agents.index(agent_step))
    app.action_hooks_or_collapse()
    assert app.current_idx == agents.index(family)

    app = _StubApp(agents, current_idx=agents.index(bash_step))
    app.action_hooks_or_collapse()
    assert app.current_idx == agents.index(bash_step)
    assert app._current_group_key is None
    assert app._group_fold_registry.snapshot() == ()


def test_h_direct_clan_member_navigates_to_clan_then_tribe() -> None:
    direct = _agent(raw_suffix="direct", tribe="research")
    direct.agent_clan = "research"
    direct.agent_clan_generation = "generation"
    projected = project_clan_tree([direct, _agent(raw_suffix="ops", tribe="ops")])
    clan = projected[0]
    app = _StubApp(projected, current_idx=projected.index(direct))
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "clan"
    app.action_hooks_or_collapse()
    assert app.current_idx == projected.index(clan)
    app.action_hooks_or_collapse()
    assert app._expanded_panel_focus is True


def test_h_rejects_stale_ambiguous_and_self_referential_parent_edges() -> None:
    agents, _family, member = _sequential_family(tribe="research")
    agents.append(_agent(raw_suffix="ops", tribe="ops"))
    member.tree_parent_key = "missing"
    member.tree_depth = 1
    stale = _StubApp(agents, current_idx=agents.index(member))
    stale._panel_group.focused_idx = stale._panel_group.panel_keys.index("research")
    assert stale._resolve_agent_left_navigation_target() is None
    stale.action_hooks_or_collapse()
    assert stale.current_idx == agents.index(member)
    assert stale._expanded_panel_focus is False

    ambiguous_agents, _family, member = _sequential_family(tribe="research")
    duplicate = _agent(raw_suffix="family", tribe="research")
    ambiguous_agents.append(duplicate)
    ambiguous_agents.append(_agent(raw_suffix="ops", tribe="ops"))
    ambiguous = _StubApp(
        ambiguous_agents,
        current_idx=ambiguous_agents.index(member),
    )
    ambiguous._panel_group.focused_idx = ambiguous._panel_group.panel_keys.index(
        "research"
    )
    assert ambiguous._resolve_agent_left_navigation_target() is None
    ambiguous.action_hooks_or_collapse()
    assert ambiguous._expanded_panel_focus is False

    self_agents, _family, self_member = _sequential_family(tribe="research")
    self_agents.append(_agent(raw_suffix="ops", tribe="ops"))
    self_member.tree_parent_key = self_member.raw_suffix
    self_member.tree_depth = 1
    self_ref = _StubApp(
        self_agents,
        current_idx=self_agents.index(self_member),
    )
    self_ref._panel_group.focused_idx = self_ref._panel_group.panel_keys.index(
        "research"
    )
    assert self_ref._resolve_agent_left_navigation_target() is None
    self_ref.action_hooks_or_collapse()
    assert self_ref._expanded_panel_focus is False


def test_h_grouping_banner_selects_tribe_and_selected_panel_has_no_parent() -> None:
    research = _agent(raw_suffix="research", tribe="research")
    ops = _agent(raw_suffix="ops", tribe="ops")
    app = _StubApp([research, ops], current_idx=0)
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")

    app._current_group_key = ("proj", "demo")
    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "tribe"
    app.action_hooks_or_collapse()

    assert app._expanded_panel_focus is True
    assert app._panel_selection_memory["research"] == (
        "banner",
        ("proj", "demo"),
    )
    assert app._resolve_agent_left_navigation_target() is None


def test_h_top_level_to_tribe_is_safe_in_single_and_merged_layouts() -> None:
    single = _StubApp([_agent(raw_suffix="single")])
    merged = _StubApp(
        [
            _agent(raw_suffix="research", tribe="research"),
            _agent(raw_suffix="ops", tribe="ops"),
        ]
    )
    merged._agent_panels_grouped = True

    single.action_hooks_or_collapse()
    merged.action_hooks_or_collapse()

    assert single._expanded_panel_focus is False
    assert merged._expanded_panel_focus is False


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
    app.action_hooks_or_collapse_all()
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    assert app.refilter_calls == 2


def test_clan_member_l_l_and_child_member_capital_h_are_isolated() -> None:
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
    app.action_hooks_or_collapse_all()
    assert app._fold_manager.get(workflow_key) is FoldLevel.EXPANDED
    assert app.current_idx == projected.index(workflow)

    app.action_hooks_or_collapse_all()
    assert app._fold_manager.get(workflow_key) is FoldLevel.COLLAPSED
    assert app.current_idx == projected.index(workflow)

    app.action_hooks_or_collapse_all()
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
    app.action_hooks_or_collapse_all()
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(member_key) is FoldLevel.EXPANDED

    app.action_expand_or_layout()
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(member_key) is FoldLevel.EXPANDED


def test_per_workflow_capital_h_runs_before_group_collapse() -> None:
    """Per-workflow ``H`` beats group collapse for an expanded workflow."""
    parent = _agent(raw_suffix="ts1", agent_type=AgentType.WORKFLOW)
    app = _StubApp([parent])
    app._fold_counts["ts1"] = (1, 0)
    app._fold_manager.expand("ts1")  # EXPANDED

    app.action_hooks_or_collapse_all()
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
    no_tribe = _agent(status="DONE")
    tribe_assigned = _agent(status="DONE", tribe="research")
    app = _StubApp([no_tribe, tribe_assigned], current_idx=0)
    app._grouping_mode = GroupingMode.BY_STATUS

    app.action_hooks_or_collapse_all()

    split_done = app._group_fold_registry.for_panel(None)
    tribe_assigned_done = app._group_fold_registry.for_panel("research")
    assert split_done.is_collapsed(("Done",)) is True
    assert tribe_assigned_done.is_collapsed(("Done",)) is False

    app._panel_group.focused_idx = 1
    app.current_idx = 1
    app._current_group_key = None
    app.action_hooks_or_collapse_all()
    assert tribe_assigned_done.is_collapsed(("Done",)) is True

    app.action_expand_or_layout()
    assert tribe_assigned_done.is_collapsed(("Done",)) is False
    assert split_done.is_collapsed(("Done",)) is True

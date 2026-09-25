"""Lowercase ``h`` parent-navigation tests for the agents tab."""

from __future__ import annotations

import pytest

from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.fold_state import FoldLevel

from ._agent_fold_transition_helpers import (
    StubFoldApp,
    make_agent,
    make_loader_shaped_aliased_plan_agent_session,
    make_sequential_agent_session,
    make_standalone_workflow_lane,
)

WORKFLOW_STEP_KINDS = (
    "agent",
    "bash",
    "python",
    "pre_prompt",
    "parallel",
    "embedded",
    "compatibility",
)


def test_h_walks_member_agent_session_clan_tribe_without_changing_folds() -> None:
    projected, session, member = make_sequential_agent_session(
        clan="research",
        tribe="research",
    )
    clan = projected[0]
    projected.append(make_agent(raw_suffix="ops", tribe="ops"))
    app = StubFoldApp(projected, current_idx=projected.index(member))
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")
    agent_session_key = agent_fold_key(session)
    clan_key = agent_fold_key(clan)
    assert agent_session_key is not None
    assert clan_key is not None
    app._fold_manager.expand(clan_key)
    app._fold_manager.expand(agent_session_key)
    tree_folds_before = app._fold_manager.snapshot()
    group_folds_before = app._group_fold_registry.snapshot()
    panel_folds_before = (
        set(app._collapsed_panel_keys),
        set(app._expanded_panel_keys),
    )

    app.action_hooks_or_collapse()
    assert app.current_idx == projected.index(session)
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
    projected, session, member = make_sequential_agent_session(clan="research")
    app = StubFoldApp(projected, current_idx=projected.index(member))
    app.current_attempt_number = 3
    app._current_group_key = None

    app.action_hooks_or_collapse()

    agent_session_idx = projected.index(session)
    member_idx = projected.index(member)
    assert app.current_idx == agent_session_idx
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app._panel_selection_memory[None] == ("agent", agent_session_idx)
    assert app.armed_departures == [member]
    assert app.acknowledged == [session]

    assert app._restore_agents_jump_anchor() is True
    assert app.current_idx == member_idx

    forward = app._entry_jump_agents_forward_stack()
    agent_session_anchor = app._pop_agents_jump_anchor(forward)
    assert agent_session_anchor == ("agent", agent_session_idx, None)
    current = app._current_agents_jump_anchor()
    assert current is not None
    app._push_agents_jump_anchor(app._entry_jump_agents_anchor_stack, current)
    app._restore_agents_jump_anchor_value(agent_session_anchor)
    assert app.current_idx == agent_session_idx


def test_h_parent_ladder_is_grouping_mode_independent() -> None:
    projected, session, member = make_sequential_agent_session(
        clan="research",
        status="RUNNING",
    )
    clan = projected[0]
    app = StubFoldApp(projected, current_idx=projected.index(member))
    app._grouping_mode = GroupingMode.BY_STATUS

    app.action_hooks_or_collapse()
    assert app.current_idx == projected.index(session)
    app.action_hooks_or_collapse()
    assert app.current_idx == projected.index(clan)
    assert app._group_fold_registry.snapshot() == ()


def test_h_loader_aliased_plan_agent_session_reaches_root_and_sole_default_panel() -> (
    None
):
    agents, root, main, coder, _steps = make_loader_shaped_aliased_plan_agent_session()
    app = StubFoldApp(agents, current_idx=agents.index(coder))
    app._grouping_mode = GroupingMode.BY_STATUS
    tree_folds_before = app._fold_manager.snapshot()
    group_folds_before = app._group_fold_registry.snapshot()
    panel_folds_before = (
        set(app._collapsed_panel_keys),
        set(app._expanded_panel_keys),
    )

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "session"
    app.action_hooks_or_collapse()
    assert app._agents[app.current_idx] is root
    assert app.acknowledged == [root]
    assert app.armed_departures == [coder]

    app.current_idx = agents.index(main)
    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "session"
    app.action_hooks_or_collapse()
    assert app._agents[app.current_idx] is root

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "tribe"
    app.action_hooks_or_collapse()

    assert app._expanded_panel_focus is True
    assert app._panel_selection_memory[None] == ("agent", agents.index(root))
    assert app._fold_manager.snapshot() == tree_folds_before
    assert app._group_fold_registry.snapshot() == group_folds_before
    assert (
        app._collapsed_panel_keys,
        app._expanded_panel_keys,
    ) == panel_folds_before


@pytest.mark.parametrize("step_kind", WORKFLOW_STEP_KINDS)
def test_h_loader_aliased_plan_agent_session_accepts_every_workflow_step_kind(
    step_kind: str,
) -> None:
    agents, root, _main, _coder, steps = make_loader_shaped_aliased_plan_agent_session()
    selected = steps[step_kind]
    app = StubFoldApp(agents, current_idx=agents.index(selected))
    app._grouping_mode = GroupingMode.BY_STATUS
    tree_folds_before = app._fold_manager.snapshot()
    group_folds_before = app._group_fold_registry.snapshot()
    panel_folds_before = (
        set(app._collapsed_panel_keys),
        set(app._expanded_panel_keys),
    )

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "session"
    app.action_hooks_or_collapse()

    assert app._agents[app.current_idx] is root
    assert app.acknowledged == [root]
    assert app.armed_departures == [selected]
    assert app._fold_manager.snapshot() == tree_folds_before
    assert app._group_fold_registry.snapshot() == group_folds_before
    assert (
        app._collapsed_panel_keys,
        app._expanded_panel_keys,
    ) == panel_folds_before


def test_h_loader_aliased_plan_agent_session_keeps_duplicate_owner_rejection() -> None:
    agents, root, _main, coder, _steps = make_loader_shaped_aliased_plan_agent_session()
    duplicate = make_agent(raw_suffix="20260720120000")
    agents.append(duplicate)
    app = StubFoldApp(agents, current_idx=agents.index(coder))

    assert app._resolve_agent_left_navigation_target() is None
    app.action_hooks_or_collapse()

    assert app.current_idx == agents.index(coder)
    assert app._expanded_panel_focus is False

    repeated_owner_agents = [*agents[:-1], root]
    repeated_owner = StubFoldApp(
        repeated_owner_agents,
        current_idx=repeated_owner_agents.index(coder),
    )
    assert repeated_owner._resolve_agent_left_navigation_target() is None


def test_h_standalone_agent_session_member_then_top_level_agent_session_selects_tribe() -> (
    None
):
    agents, session, member = make_sequential_agent_session(tribe="research")
    agents.append(make_agent(raw_suffix="ops", tribe="ops"))
    app = StubFoldApp(agents, current_idx=agents.index(member))
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")

    app.action_hooks_or_collapse()
    assert app.current_idx == agents.index(session)
    assert app._group_fold_registry.snapshot() == ()

    app.action_hooks_or_collapse()
    assert app._expanded_panel_focus is True
    assert app._group_fold_registry.snapshot() == ()


@pytest.mark.parametrize("step_kind", WORKFLOW_STEP_KINDS)
def test_h_standalone_workflow_steps_navigate_to_workflow_owner(
    step_kind: str,
) -> None:
    agents, root, steps = make_standalone_workflow_lane()
    selected = steps[step_kind]
    app = StubFoldApp(agents, current_idx=agents.index(selected))

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "workflow"
    app.action_hooks_or_collapse()

    assert app._agents[app.current_idx] is root
    assert app._panel_selection_memory[None] == ("agent", agents.index(root))


def test_h_clan_workflow_step_walks_workflow_clan_tribe_one_level_at_a_time() -> None:
    projected, root, steps = make_standalone_workflow_lane(
        clan="research",
        tribe="research",
    )
    projected.append(make_agent(raw_suffix="ops", tribe="ops"))
    clan = projected[0]
    selected = steps["python"]
    app = StubFoldApp(projected, current_idx=projected.index(selected))
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "workflow"
    app.action_hooks_or_collapse()
    assert app._agents[app.current_idx] is root

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "clan"
    app.action_hooks_or_collapse()
    assert app._agents[app.current_idx] is clan

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "tribe"
    app.action_hooks_or_collapse()
    assert app._expanded_panel_focus is True


def test_h_workflow_step_jump_history_restores_exact_script_row() -> None:
    agents, root, steps = make_standalone_workflow_lane()
    selected = steps["python"]
    app = StubFoldApp(agents, current_idx=agents.index(selected))

    app.action_hooks_or_collapse()

    assert app._agents[app.current_idx] is root
    assert app._restore_agents_jump_anchor() is True
    assert app._agents[app.current_idx] is selected


def test_h_nested_monitor_navigates_to_starter() -> None:
    agent_session = make_agent(raw_suffix="session", tribe="research")
    agent_session.plan_chain_root = True
    agent_session.agent_session = "session"
    agent_session.agent_clan = "research"
    agent_session.agent_clan_generation = "generation"
    member = make_agent(raw_suffix="member")
    member.parent_timestamp = agent_session.raw_suffix
    member.agent_session = "session"
    member.agent_session_role = "code"
    monitor = make_agent(raw_suffix="monitor")
    monitor.parent_timestamp = member.raw_suffix
    monitor.agent_session = "session"
    monitor.agent_session_role = "monitor"
    agent_session.followup_agents.append(member)
    agent_session.runtime_children.append(member)
    member.runtime_children.append(monitor)
    projected = project_clan_tree([agent_session, member, monitor])
    app = StubFoldApp(projected, current_idx=projected.index(monitor))
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "workflow"
    assert target.agent is member
    app.action_hooks_or_collapse()
    assert app.current_idx == projected.index(member)


def _make_nested_monitor_agent_session() -> tuple[
    list[Agent], Agent, Agent, Agent, Agent
]:
    """Clan -> session root -> mid-session starter -> disk-shaped monitor."""
    agent_session = make_agent(raw_suffix="session", tribe="research")
    agent_session.plan_chain_root = True
    agent_session.agent_session = "session"
    agent_session.agent_clan = "research"
    agent_session.agent_clan_generation = "generation"
    member = make_agent(raw_suffix="member")
    member.parent_timestamp = agent_session.raw_suffix
    member.agent_session = "session"
    member.agent_session_role = "code"
    monitor = make_agent(raw_suffix="monitor")
    monitor.parent_timestamp = member.raw_suffix
    monitor.agent_session = "session"
    monitor.agent_session_role = "monitor"
    agent_session.followup_agents.append(member)
    agent_session.runtime_children.append(member)
    member.runtime_children.append(monitor)
    projected = project_clan_tree([agent_session, member, monitor])
    container = projected[0]
    return projected, container, agent_session, member, monitor


def test_l_on_agent_session_container_reveals_monitor_nested_under_mid_session_starter() -> (
    None
):
    projected, container, agent_session, member, monitor = (
        _make_nested_monitor_agent_session()
    )
    clan_key = agent_fold_key(container)
    agent_session_key = agent_fold_key(agent_session)
    assert clan_key is not None
    assert agent_session_key is not None
    app = StubFoldApp(projected, current_idx=projected.index(agent_session))
    app._fold_manager.expand(clan_key)

    app.action_expand_or_layout()

    assert app._fold_manager.get(agent_session_key) is FoldLevel.EXPANDED
    visible, _counts = filter_agents_by_fold_state(projected, app._fold_manager)
    assert member in visible
    assert monitor in visible


def test_l_on_selected_monitor_targets_session_fold_not_starter() -> None:
    projected, container, agent_session, member, monitor = (
        _make_nested_monitor_agent_session()
    )
    clan_key = agent_fold_key(container)
    agent_session_key = agent_fold_key(agent_session)
    member_key = agent_fold_key(member)
    assert clan_key is not None
    assert agent_session_key is not None
    app = StubFoldApp(projected, current_idx=projected.index(monitor))
    app._fold_manager.expand(clan_key)

    assert app._get_workflow_key_for_agent(monitor) == agent_session_key
    assert app._get_workflow_key_for_agent(monitor) != member_key

    app.action_expand_or_layout()

    assert app._fold_manager.get(agent_session_key) is FoldLevel.EXPANDED


def test_capital_h_on_selected_monitor_collapses_agent_session_and_reanchors() -> None:
    projected, container, agent_session, member, monitor = (
        _make_nested_monitor_agent_session()
    )
    clan_key = agent_fold_key(container)
    agent_session_key = agent_fold_key(agent_session)
    assert clan_key is not None
    assert agent_session_key is not None
    app = StubFoldApp(projected, current_idx=projected.index(monitor))
    app._fold_manager.expand(clan_key)
    app._fold_manager.expand(agent_session_key)

    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(agent_session_key) is FoldLevel.COLLAPSED
    assert app.current_idx == projected.index(agent_session)


def test_h_direct_clan_member_navigates_to_clan_then_tribe() -> None:
    direct = make_agent(raw_suffix="direct", tribe="research")
    direct.agent_clan = "research"
    direct.agent_clan_generation = "generation"
    projected = project_clan_tree([direct, make_agent(raw_suffix="ops", tribe="ops")])
    clan = projected[0]
    app = StubFoldApp(projected, current_idx=projected.index(direct))
    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")

    target = app._resolve_agent_left_navigation_target()
    assert target is not None and target.kind == "clan"
    app.action_hooks_or_collapse()
    assert app.current_idx == projected.index(clan)
    app.action_hooks_or_collapse()
    assert app._expanded_panel_focus is True


def test_h_rejects_stale_ambiguous_and_self_referential_parent_edges() -> None:
    agents, _family, member = make_sequential_agent_session(tribe="research")
    agents.append(make_agent(raw_suffix="ops", tribe="ops"))
    member.tree_parent_key = "missing"
    member.tree_depth = 1
    stale = StubFoldApp(agents, current_idx=agents.index(member))
    stale._panel_group.focused_idx = stale._panel_group.panel_keys.index("research")
    assert stale._resolve_agent_left_navigation_target() is None
    stale.action_hooks_or_collapse()
    assert stale.current_idx == agents.index(member)
    assert stale._expanded_panel_focus is False

    ambiguous_agents, _family, member = make_sequential_agent_session(tribe="research")
    duplicate = make_agent(raw_suffix="session", tribe="research")
    ambiguous_agents.append(duplicate)
    ambiguous_agents.append(make_agent(raw_suffix="ops", tribe="ops"))
    ambiguous = StubFoldApp(
        ambiguous_agents,
        current_idx=ambiguous_agents.index(member),
    )
    ambiguous._panel_group.focused_idx = ambiguous._panel_group.panel_keys.index(
        "research"
    )
    assert ambiguous._resolve_agent_left_navigation_target() is None
    ambiguous.action_hooks_or_collapse()
    assert ambiguous._expanded_panel_focus is False

    self_agents, _family, self_member = make_sequential_agent_session(tribe="research")
    self_agents.append(make_agent(raw_suffix="ops", tribe="ops"))
    self_member.tree_parent_key = self_member.raw_suffix
    self_member.tree_depth = 1
    self_ref = StubFoldApp(
        self_agents,
        current_idx=self_agents.index(self_member),
    )
    self_ref._panel_group.focused_idx = self_ref._panel_group.panel_keys.index(
        "research"
    )
    assert self_ref._resolve_agent_left_navigation_target() is None
    self_ref.action_hooks_or_collapse()
    assert self_ref._expanded_panel_focus is False


def test_h_rejects_cycles_and_inconsistent_tree_depth() -> None:
    agents, _root, steps = make_standalone_workflow_lane()
    inconsistent = steps["python"]
    inconsistent.tree_depth = 3
    bad_depth = StubFoldApp(agents, current_idx=agents.index(inconsistent))
    assert bad_depth._resolve_agent_left_navigation_target() is None

    first = make_agent(raw_suffix="first", agent_type=AgentType.WORKFLOW)
    second = make_agent(raw_suffix="second", agent_type=AgentType.WORKFLOW)
    first.parent_timestamp = second.raw_suffix
    first.parent_workflow = "cycle"
    second.parent_timestamp = first.raw_suffix
    second.parent_workflow = "cycle"
    cycle = StubFoldApp([first, second])
    assert cycle._resolve_agent_left_navigation_target() is None


def test_h_rejects_conflicting_explicit_and_persisted_parent_keys() -> None:
    agents, root, steps = make_standalone_workflow_lane()
    selected = steps["bash"]
    selected.tree_parent_key = root.raw_suffix
    selected.tree_depth = 1
    selected.parent_timestamp = "different-owner"
    app = StubFoldApp(agents, current_idx=agents.index(selected))

    assert app._resolve_agent_left_navigation_target() is None


def test_h_rejects_orphan_script_and_duplicate_top_level_owner() -> None:
    orphan = make_agent(raw_suffix="orphan", agent_type=AgentType.WORKFLOW)
    orphan.step_type = "bash"
    orphan_app = StubFoldApp([orphan])
    assert orphan_app._resolve_agent_left_navigation_target() is None

    first = make_agent(raw_suffix="duplicate")
    second = make_agent(raw_suffix="duplicate")
    duplicate_app = StubFoldApp([first, second])
    assert duplicate_app._resolve_agent_left_navigation_target() is None


def test_h_grouping_banner_selects_tribe_and_selected_panel_has_no_parent() -> None:
    research = make_agent(raw_suffix="research", tribe="research")
    ops = make_agent(raw_suffix="ops", tribe="ops")
    app = StubFoldApp([research, ops], current_idx=0)
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


def test_h_top_level_selects_single_split_tribe_but_not_merged_layout() -> None:
    single = StubFoldApp([make_agent(raw_suffix="single")])
    merged = StubFoldApp(
        [
            make_agent(raw_suffix="research", tribe="research"),
            make_agent(raw_suffix="ops", tribe="ops"),
        ]
    )
    merged._agent_panels_grouped = True

    single.action_hooks_or_collapse()
    merged.action_hooks_or_collapse()

    assert single._expanded_panel_focus is True
    assert single._panel_selection_memory[None] == ("agent", 0)
    assert merged._expanded_panel_focus is False

"""Per-group agents-tab fold transition tests."""

from __future__ import annotations

from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.fold_state import FoldLevel

from ._agent_fold_transition_helpers import (
    StubFoldApp,
    make_agent,
    make_sequential_family,
    make_standalone_workflow_lane,
)


def _named_workflow_lane(
    name: str,
    *,
    tribe: str | None = None,
) -> tuple[list[Agent], Agent]:
    rows, root, steps = make_standalone_workflow_lane(tribe=tribe)
    fold_key = f"{name}-fold"
    root.cl_name = name
    root.agent_name = name
    root.raw_suffix = fold_key
    for step in steps.values():
        step.raw_suffix = fold_key
        step.parent_timestamp = fold_key
    return rows, root


def _named_family_lane(name: str) -> tuple[list[Agent], Agent]:
    rows, root, member = make_sequential_family()
    fold_key = f"{name}-fold"
    root.cl_name = name
    root.agent_name = name
    root.agent_family = name
    root.raw_suffix = fold_key
    member.cl_name = f"{name}-member"
    member.agent_name = f"{name}--code"
    member.agent_family = name
    member.parent_timestamp = fold_key
    return rows, root


def _sync_fold_projection(
    app: StubFoldApp,
    all_agents: list[Agent],
    selected: Agent,
    *,
    merged: bool = False,
) -> None:
    app._agents, app._fold_counts = filter_agents_by_fold_state(
        all_agents,
        app._fold_manager,
    )
    app.current_idx = app._agents.index(selected)
    app._agent_panels_grouped = merged
    app._panel_group = AgentPanelGroup.from_agents(
        app._agents,
        merge_tribe_panels=merged,
    )


def test_capital_h_on_agent_collapses_only_its_group() -> None:
    """Two projects A + B; pressing ``H`` in A leaves B untouched."""
    a = make_agent(cl_name="cl-a", project="projA")
    b = make_agent(cl_name="cl-b", project="projB")
    app = StubFoldApp([a, b], current_idx=0)

    app.action_hooks_or_collapse_all()

    assert app._group_fold_registry.is_collapsed(("projA", "cl-a")) is True
    assert app._group_fold_registry.is_collapsed(("projB", "cl-b")) is False
    assert app._current_group_key == ("projA", "cl-a")


def test_capital_h_inside_l1_collapses_l1_then_parent_l0() -> None:
    """Focus inside an L1: first ``H`` collapses L1, second collapses L0."""
    a = make_agent(agent_name="coder.claude")
    b = make_agent(agent_name="coder.codex")
    app = StubFoldApp([a, b], current_idx=0)
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
    """``l`` while focused on a collapsed L1 expands only that group."""
    a = make_agent(agent_name="coder.claude")
    b = make_agent(agent_name="coder.codex")
    c = make_agent(agent_name="planner.claude")
    d = make_agent(agent_name="planner.codex")
    app = StubFoldApp([a, b, c, d], current_idx=0)
    coder = ("proj", "demo", "coder")
    planner = ("proj", "demo", "planner")
    app._group_fold_registry.collapse(coder)
    app._group_fold_registry.collapse(planner)
    app._current_group_key = coder

    app.action_expand_or_layout()

    assert app._group_fold_registry.is_collapsed(coder) is False
    assert app._group_fold_registry.is_collapsed(planner) is True


def test_l_expands_agent_fold_without_artifact_pane_focus() -> None:
    a = make_agent(agent_name="coder.claude")
    app = StubFoldApp([a], current_idx=0)
    key = ("proj", "demo", "coder")
    app._group_fold_registry.collapse(key)
    app._current_group_key = key
    app.focus_artifact_result = True

    app.action_expand_or_layout()

    assert app.focus_artifact_calls == 0
    assert app._group_fold_registry.is_collapsed(key) is False
    assert app.refilter_calls == 1


def test_capital_h_then_l_round_trip_clears_group_focus() -> None:
    """After ``H`` snaps to a banner, ``l`` expands and clears its focus."""
    a = make_agent(cl_name="cl-a", project="projA")
    app = StubFoldApp([a], current_idx=0)
    key = ("projA", "cl-a")

    app.action_hooks_or_collapse_all()
    assert app._current_group_key == key
    assert app._group_fold_registry.is_collapsed(key) is True

    app.action_expand_or_layout()
    assert app._group_fold_registry.is_collapsed(key) is False
    assert app._current_group_key is None


def test_equal_status_group_keys_fold_independently_between_panels() -> None:
    no_tribe = make_agent(status="DONE")
    tribe_assigned = make_agent(status="DONE", tribe="research")
    app = StubFoldApp([no_tribe, tribe_assigned], current_idx=0)
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


def test_capital_h_collapses_every_open_lane_before_status_group() -> None:
    hu_rows, hu = _named_workflow_lane("hu")
    ht_rows, ht = _named_workflow_lane("ht")
    hs_rows, hs = _named_family_lane("hs")
    agents = [*hu_rows, *ht_rows, *hs_rows]
    app = StubFoldApp(agents, current_idx=agents.index(hu))
    app._grouping_mode = GroupingMode.BY_STATUS
    ht_key = agent_fold_key(ht)
    hs_key = agent_fold_key(hs)
    assert ht_key is not None and hs_key is not None
    app._fold_manager.expand(ht_key)
    app._fold_manager.expand(hs_key)
    app._fold_manager.expand(hs_key)
    _sync_fold_projection(app, agents, hu)

    target = app._resolve_sase_agent_collapse_target()
    assert target is not None
    assert target.group_key == ("Running",)
    assert set(target.fold_keys) == {ht_key, hs_key}

    app.action_hooks_or_collapse_all()

    assert app.current_idx == app._agents.index(hu)
    assert app._fold_manager.get(ht_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(hs_key) is FoldLevel.COLLAPSED
    assert not app._group_fold_registry.is_collapsed(("Running",))
    assert app.refilter_calls == 1
    assert app.refilter_kwargs == [{"prior_pos": None, "refresh_content_index": False}]
    assert app.group_fold_changes == []

    app.action_hooks_or_collapse_all()

    assert app._group_fold_registry.is_collapsed(("Running",))
    assert app.refilter_calls == 2
    assert app.group_fold_changes == [(None, ("Running",), True)]


def test_lane_collapse_reanchors_each_disappearing_child_kind() -> None:
    rows, root = _named_workflow_lane("selected")
    family_rows, family = _named_family_lane("family")
    agents = [*rows, *family_rows]
    app = StubFoldApp(agents)
    app._grouping_mode = GroupingMode.BY_DATE
    root_key = agent_fold_key(root)
    family_key = agent_fold_key(family)
    assert root_key is not None and family_key is not None

    disappearing = [
        candidate
        for candidate in rows
        if candidate.is_workflow_step_child
        and candidate.step_type in {"agent", "bash", "python"}
    ]
    disappearing.append(family_rows[1])
    for selected in disappearing:
        app._fold_manager.expand(root_key)
        app._fold_manager.expand(root_key)
        app._fold_manager.expand(family_key)
        _sync_fold_projection(app, agents, selected)
        app._current_group_key = None

        app.action_hooks_or_collapse_all()

        expected_owner = family if selected is family_rows[1] else root
        assert app.current_idx == app._agents.index(expected_owner)
        assert app._panel_selection_memory[None] == (
            "agent",
            app._agents.index(expected_owner),
        )
        assert app._fold_manager.get(root_key) is FoldLevel.COLLAPSED
        assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED


def test_collapsed_child_banner_scopes_lane_step_to_its_open_parent() -> None:
    first_rows, first = _named_workflow_lane("coder.claude")
    second_rows, second = _named_workflow_lane("coder.codex")
    agents = [*first_rows, *second_rows]
    app = StubFoldApp(agents, current_idx=agents.index(first))
    app._grouping_mode = GroupingMode.BY_STATUS
    first_key = agent_fold_key(first)
    second_key = agent_fold_key(second)
    assert first_key is not None and second_key is not None
    app._fold_manager.expand(first_key)
    app._fold_manager.expand(second_key)
    _sync_fold_projection(app, agents, first)
    child_group = ("Running", "coder")
    parent_group = ("Running",)
    app._group_fold_registry.collapse(child_group)
    app._current_group_key = child_group

    target = app._resolve_sase_agent_collapse_target()
    assert target is not None
    assert target.group_key == parent_group

    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(first_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(second_key) is FoldLevel.COLLAPSED
    assert app._group_fold_registry.is_collapsed(child_group)
    assert not app._group_fold_registry.is_collapsed(parent_group)
    assert app._current_group_key == child_group

    app.action_hooks_or_collapse_all()
    assert app._group_fold_registry.is_collapsed(parent_group)


def test_lane_collapse_isolated_by_panel_and_merged_layout() -> None:
    selector = make_agent(agent_name="selector")
    default_rows, default = _named_workflow_lane("default")
    tribe_rows, tribe = _named_workflow_lane("research", tribe="research")
    agents = [selector, *default_rows, *tribe_rows]
    default_key = agent_fold_key(default)
    tribe_key = agent_fold_key(tribe)
    assert default_key is not None and tribe_key is not None

    split = StubFoldApp(agents, current_idx=agents.index(selector))
    split._grouping_mode = GroupingMode.BY_STATUS
    split._fold_manager.expand(default_key)
    split._fold_manager.expand(tribe_key)
    _sync_fold_projection(split, agents, selector)
    split.action_hooks_or_collapse_all()
    assert split._fold_manager.get(default_key) is FoldLevel.COLLAPSED
    assert split._fold_manager.get(tribe_key) is FoldLevel.EXPANDED

    merged = StubFoldApp(agents, current_idx=agents.index(selector))
    merged._grouping_mode = GroupingMode.BY_STATUS
    merged._fold_manager.expand(default_key)
    merged._fold_manager.expand(tribe_key)
    _sync_fold_projection(merged, agents, selector, merged=True)
    merged.action_hooks_or_collapse_all()
    assert merged._fold_manager.get(default_key) is FoldLevel.COLLAPSED
    assert merged._fold_manager.get(tribe_key) is FoldLevel.COLLAPSED


def test_malformed_lane_fails_closed_while_valid_sibling_collapses() -> None:
    closed_rows, closed = _named_workflow_lane("closed")
    valid_rows, valid = _named_workflow_lane("valid")
    malformed_rows, malformed = _named_workflow_lane("malformed")
    malformed.tree_depth = 1
    agents = [*closed_rows, *valid_rows, *malformed_rows]
    app = StubFoldApp(agents, current_idx=agents.index(closed))
    app._grouping_mode = GroupingMode.BY_STATUS
    valid_key = agent_fold_key(valid)
    malformed_key = agent_fold_key(malformed)
    assert valid_key is not None and malformed_key is not None
    app._fold_manager.expand(valid_key)
    app._fold_manager.expand(malformed_key)
    _sync_fold_projection(app, agents, closed)

    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(valid_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(malformed_key) is FoldLevel.EXPANDED
    assert not app._group_fold_registry.is_collapsed(("Running",))


def test_duplicate_lane_owner_is_not_mutated_as_a_bulk_candidate() -> None:
    closed_rows, closed = _named_workflow_lane("closed")
    first_rows, first = _named_workflow_lane("duplicate")
    second_rows, second = _named_workflow_lane("other")
    duplicate_key = agent_fold_key(first)
    assert duplicate_key is not None
    second.raw_suffix = duplicate_key
    second.tribe = "research"
    for child in second_rows[1:]:
        child.raw_suffix = duplicate_key
        child.parent_timestamp = duplicate_key
    agents = [*closed_rows, *first_rows, *second_rows]
    app = StubFoldApp(agents, current_idx=agents.index(closed))
    app._grouping_mode = GroupingMode.BY_STATUS
    app._fold_manager.expand(duplicate_key)
    _sync_fold_projection(app, agents, closed)

    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(duplicate_key) is FoldLevel.EXPANDED
    assert app._group_fold_registry.is_collapsed(("Running",))

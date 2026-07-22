"""Group-scoped clan rung coverage for the uppercase-H ladder."""

from __future__ import annotations

from datetime import timedelta

from sase.core.time import local_now

from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldLevel

from ._agent_fold_transition_helpers import (
    StubFoldApp,
    make_agent,
    make_sequential_family,
)


def _clan_member(
    clan: str,
    *,
    status: str = "RUNNING",
    tribe: str | None = None,
    generation: str = "generation",
) -> Agent:
    member = make_agent(
        cl_name=f"{clan}-member",
        agent_name=f"{clan}.worker",
        raw_suffix=f"{clan}-{generation}-member",
        status=status,
        tribe=tribe,
    )
    member.agent_clan = clan
    member.agent_clan_generation = generation
    return member


def _projected_clan(
    clan: str,
    *,
    status: str = "RUNNING",
    tribe: str | None = None,
) -> list[Agent]:
    return project_clan_tree([_clan_member(clan, status=status, tribe=tribe)])


def _clan_container(agents: list[Agent], clan: str) -> Agent:
    return next(
        row for row in agents if row.is_clan_container and row.agent_clan == clan
    )


def _sync_fold_projection(
    app: StubFoldApp,
    all_agents: list[Agent],
    selected: Agent,
    *,
    focused_key: str | None = None,
    merged: bool = False,
) -> None:
    app._agents_with_children = list(all_agents)
    app._agents, app._fold_counts = filter_agents_by_fold_state(
        all_agents,
        app._fold_manager,
    )
    app.current_idx = app._agents.index(selected)
    app._agent_panels_grouped = merged
    app._panel_group = AgentPanelGroup.from_agents(
        app._agents,
        focused_key=focused_key,
        merge_tribe_panels=merged,
    )


def test_row_h_collapses_sibling_clan_before_status_group() -> None:
    open_rows = _projected_clan("sase-8k", tribe="epic")
    selected_rows = _projected_clan("sase-8l", tribe="epic")
    agents = [*open_rows, *selected_rows]
    open_clan = _clan_container(agents, "sase-8k")
    selected_clan = _clan_container(agents, "sase-8l")
    open_key = agent_fold_key(open_clan)
    assert open_key is not None

    app = StubFoldApp(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._fold_manager.expand(open_key)
    _sync_fold_projection(app, agents, selected_clan, focused_key="epic")
    selected_idx = app.current_idx
    selected_memory = ("agent", selected_idx)
    app._panel_selection_memory["epic"] = selected_memory
    history = [("agent", selected_clan.identity)]
    app._entry_jump_agents_anchor_stack = list(history)

    target = app._resolve_agent_clan_collapse_target()
    assert target is not None
    assert target.panel_key == "epic"
    assert target.group_key == ("Running",)
    assert target.fold_keys == (open_key,)

    app.action_hooks_or_collapse_all()

    registry = app._group_fold_registry.for_panel("epic")
    assert app._fold_manager.get(open_key) is FoldLevel.COLLAPSED
    assert not registry.is_collapsed(("Running",))
    assert app.current_idx == selected_idx
    assert app._agents[app.current_idx] is selected_clan
    assert app._panel_selection_memory["epic"] == selected_memory
    assert app._entry_jump_agents_anchor_stack == history
    assert app.group_fold_changes == []
    assert app.refilter_kwargs == [{"prior_pos": None, "refresh_content_index": False}]

    app.action_hooks_or_collapse_all()

    assert registry.is_collapsed(("Running",))
    assert app.group_fold_changes == [(None, ("Running",), True)]


def test_row_h_closes_houses_then_all_group_clans_then_group() -> None:
    family_rows, family, _member = make_sequential_family(clan="workers")
    sibling_rows = _projected_clan("reviewers")
    closed_rows = _projected_clan("closed")
    agents = [*family_rows, *sibling_rows, *closed_rows]
    family_clan = _clan_container(agents, "workers")
    sibling_clan = _clan_container(agents, "reviewers")
    closed_clan = _clan_container(agents, "closed")
    family_key = agent_fold_key(family)
    family_clan_key = agent_fold_key(family_clan)
    sibling_key = agent_fold_key(sibling_clan)
    assert family_key is not None
    assert family_clan_key is not None
    assert sibling_key is not None

    app = StubFoldApp(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._fold_manager.expand(family_key)
    app._fold_manager.expand(family_key)
    app._fold_manager.expand(family_clan_key)
    app._fold_manager.expand(sibling_key)
    _sync_fold_projection(app, agents, closed_clan)

    app.action_hooks_or_collapse_all()

    registry = app._group_fold_registry.for_panel(None)
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(family_clan_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(sibling_key) is FoldLevel.EXPANDED
    assert not registry.is_collapsed(("Running",))

    target = app._resolve_agent_clan_collapse_target()
    assert target is not None
    assert target.fold_keys == (family_clan_key, sibling_key)
    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(family_clan_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(sibling_key) is FoldLevel.COLLAPSED
    assert not registry.is_collapsed(("Running",))

    app.action_hooks_or_collapse_all()
    assert registry.is_collapsed(("Running",))


def test_group_clan_scope_isolates_status_panel_and_merged_layout() -> None:
    open_rows = _projected_clan("open")
    selected_rows = _projected_clan("selected")
    done_rows = _projected_clan("done", status="DONE")
    other_panel_rows = _projected_clan("other-panel", tribe="research")
    agents = [*open_rows, *selected_rows, *done_rows, *other_panel_rows]
    selected = _clan_container(agents, "selected")
    open_key = agent_fold_key(_clan_container(agents, "open"))
    done_key = agent_fold_key(_clan_container(agents, "done"))
    other_panel_key = agent_fold_key(_clan_container(agents, "other-panel"))
    assert open_key is not None and done_key is not None and other_panel_key is not None

    split = StubFoldApp(agents)
    split._grouping_mode = GroupingMode.BY_STATUS
    split._fold_manager.expand(open_key)
    split._fold_manager.expand(done_key)
    split._fold_manager.expand(other_panel_key)
    _sync_fold_projection(split, agents, selected)

    split.action_hooks_or_collapse_all()

    assert split._fold_manager.get(open_key) is FoldLevel.COLLAPSED
    assert split._fold_manager.get(done_key) is FoldLevel.EXPANDED
    assert split._fold_manager.get(other_panel_key) is FoldLevel.EXPANDED

    merged = StubFoldApp(agents)
    merged._grouping_mode = GroupingMode.BY_STATUS
    merged._fold_manager.expand(open_key)
    merged._fold_manager.expand(done_key)
    merged._fold_manager.expand(other_panel_key)
    _sync_fold_projection(merged, agents, selected, merged=True)

    target = merged._resolve_agent_clan_collapse_target()
    assert target is not None
    assert target.fold_keys == (open_key, other_panel_key)
    merged.action_hooks_or_collapse_all()

    assert merged._fold_manager.get(open_key) is FoldLevel.COLLAPSED
    assert merged._fold_manager.get(other_panel_key) is FoldLevel.COLLAPSED
    assert merged._fold_manager.get(done_key) is FoldLevel.EXPANDED


def test_group_clan_scope_isolates_date_and_project_groups() -> None:
    today_rows = _projected_clan("today")
    selected_today_rows = _projected_clan("selected-today")
    yesterday_rows = _projected_clan("yesterday")
    date_agents = [*today_rows, *selected_today_rows, *yesterday_rows]
    selected_today = _clan_container(date_agents, "selected-today")
    today_key = agent_fold_key(_clan_container(date_agents, "today"))
    yesterday_key = agent_fold_key(_clan_container(date_agents, "yesterday"))
    assert today_key is not None and yesterday_key is not None
    for row in today_rows + selected_today_rows:
        row.start_time = local_now()
    for row in yesterday_rows:
        row.start_time = local_now() - timedelta(days=1)

    by_date = StubFoldApp(date_agents)
    by_date._grouping_mode = GroupingMode.BY_DATE
    by_date._fold_manager.expand(today_key)
    by_date._fold_manager.expand(yesterday_key)
    _sync_fold_projection(by_date, date_agents, selected_today)
    by_date.action_hooks_or_collapse_all()
    assert by_date._fold_manager.get(today_key) is FoldLevel.COLLAPSED
    assert by_date._fold_manager.get(yesterday_key) is FoldLevel.EXPANDED

    coder_open_rows = _projected_clan("coder.one")
    coder_selected_rows = _projected_clan("coder.two")
    planner_one_rows = _projected_clan("planner.one")
    planner_two_rows = _projected_clan("planner.two")
    name_agents = [
        *coder_open_rows,
        *coder_selected_rows,
        *planner_one_rows,
        *planner_two_rows,
    ]
    for row in planner_one_rows + planner_two_rows:
        row.project_file = "/r/other/other.sase"
    coder_selected = _clan_container(name_agents, "coder.two")
    coder_key = agent_fold_key(_clan_container(name_agents, "coder.one"))
    planner_keys = {
        agent_fold_key(_clan_container(name_agents, "planner.one")),
        agent_fold_key(_clan_container(name_agents, "planner.two")),
    }
    assert coder_key is not None and None not in planner_keys

    by_project = StubFoldApp(name_agents)
    by_project._grouping_mode = GroupingMode.STANDARD
    by_project._fold_manager.expand(coder_key)
    for planner_key in planner_keys:
        assert planner_key is not None
        by_project._fold_manager.expand(planner_key)
    _sync_fold_projection(by_project, name_agents, coder_selected)

    target = by_project._resolve_agent_clan_collapse_target()
    assert target is not None
    assert target.group_key == ("proj",)
    assert target.fold_keys == (coder_key,)
    by_project.action_hooks_or_collapse_all()

    assert by_project._fold_manager.get(coder_key) is FoldLevel.COLLAPSED
    assert all(
        by_project._fold_manager.get(key) is FoldLevel.EXPANDED
        for key in planner_keys
        if key is not None
    )


def test_group_clan_collapse_reanchors_direct_member_once_without_persistence() -> None:
    rows = _projected_clan("workers", tribe="research")
    clan = _clan_container(rows, "workers")
    member = next(row for row in rows if not row.is_clan_container)
    clan_key = agent_fold_key(clan)
    assert clan_key is not None

    app = StubFoldApp(rows)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._fold_manager.expand(clan_key)
    _sync_fold_projection(app, rows, member, focused_key="research")

    target = app._resolve_agent_clan_collapse_target()
    assert target is not None
    assert target.reanchor_index == app._agents.index(clan)
    app.action_hooks_or_collapse_all()

    assert app.current_idx == app._agents.index(clan)
    assert app._panel_selection_memory["research"] == (
        "agent",
        app._agents.index(clan),
    )
    assert app.refilter_calls == 1
    assert app.refilter_kwargs == [{"prior_pos": None, "refresh_content_index": False}]
    assert app.group_fold_changes == []


def test_collapsed_child_banner_scopes_clan_step_to_open_parent() -> None:
    first_rows = _projected_clan("coder.alpha")
    second_rows = _projected_clan("coder.beta")
    agents = [*first_rows, *second_rows]
    first = _clan_container(agents, "coder.alpha")
    first_key = agent_fold_key(first)
    second_key = agent_fold_key(_clan_container(agents, "coder.beta"))
    assert first_key is not None and second_key is not None

    app = StubFoldApp(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._fold_manager.expand(first_key)
    app._fold_manager.expand(second_key)
    _sync_fold_projection(app, agents, first)
    child_group = ("Running", "coder")
    parent_group = ("Running",)
    registry = app._group_fold_registry.for_panel(None)
    registry.collapse(child_group)
    app._current_group_key = child_group

    target = app._resolve_agent_clan_collapse_target()
    assert target is not None
    assert target.group_key == parent_group
    assert target.fold_keys == (first_key, second_key)
    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(first_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(second_key) is FoldLevel.COLLAPSED
    assert registry.is_collapsed(child_group)
    assert not registry.is_collapsed(parent_group)
    assert app._current_group_key == child_group

    app.action_hooks_or_collapse_all()
    assert registry.is_collapsed(parent_group)


def test_malformed_and_duplicate_clans_fail_closed_per_candidate() -> None:
    valid_rows = _projected_clan("valid")
    malformed_rows = _projected_clan("malformed")
    duplicate_rows = _projected_clan("duplicate")
    other_duplicate_rows = _projected_clan("duplicate", tribe="research")
    selected_rows = _projected_clan("selected")
    malformed = _clan_container(malformed_rows, "malformed")
    malformed.tree_depth = 1
    agents = [
        *valid_rows,
        *malformed_rows,
        *duplicate_rows,
        *other_duplicate_rows,
        *selected_rows,
    ]
    valid_key = agent_fold_key(_clan_container(valid_rows, "valid"))
    malformed_key = agent_fold_key(malformed)
    duplicate_key = agent_fold_key(_clan_container(duplicate_rows, "duplicate"))
    selected = _clan_container(selected_rows, "selected")
    assert valid_key is not None and malformed_key is not None
    assert duplicate_key is not None

    app = StubFoldApp(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._fold_manager.expand(valid_key)
    app._fold_manager.expand(malformed_key)
    app._fold_manager.expand(duplicate_key)
    _sync_fold_projection(app, agents, selected)

    target = app._resolve_agent_clan_collapse_target()
    assert target is not None
    assert target.fold_keys == (valid_key,)
    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(valid_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(malformed_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(duplicate_key) is FoldLevel.EXPANDED
    assert not app._group_fold_registry.for_panel(None).is_collapsed(("Running",))

    fallback_agents = [*duplicate_rows, *other_duplicate_rows, *selected_rows]
    fallback = StubFoldApp(fallback_agents)
    fallback._grouping_mode = GroupingMode.BY_STATUS
    fallback._fold_manager.expand(duplicate_key)
    _sync_fold_projection(fallback, fallback_agents, selected)
    assert fallback._resolve_agent_clan_collapse_target() is None

    fallback.action_hooks_or_collapse_all()

    assert fallback._fold_manager.get(duplicate_key) is FoldLevel.EXPANDED
    assert fallback._group_fold_registry.for_panel(None).is_collapsed(("Running",))

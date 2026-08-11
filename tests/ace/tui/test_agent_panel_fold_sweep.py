"""Tests for the ``-`` panel fold sweep and its per-panel reverse."""

from __future__ import annotations

from sase.ace.tui.actions.agents._folding_panel_sweep import (
    _live_sweep_record_entries,
)
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import (
    AgentPanelGroup,
    PanelFoldSweepRecord,
    PanelIsolationRevert,
)
from sase.ace.tui.models.fold_state import FoldLevel

from ._agent_fold_transition_helpers import (
    make_agent as make_transition_agent,
)
from ._agent_fold_transition_helpers import (
    make_sequential_family,
    make_standalone_workflow_lane,
)
from ._agent_panel_collapse_helpers import AgentPanelCollapseApp


def _named_workflow_lane(
    name: str, *, tribe: str | None = None
) -> tuple[list[Agent], Agent, dict[str, Agent]]:
    """Build a standalone workflow lane with a unique, cross-panel-safe key."""
    rows, root, steps = make_standalone_workflow_lane(tribe=tribe)
    fold_key = f"{name}-fold"
    root.cl_name = name
    root.agent_name = name
    root.raw_suffix = fold_key
    for step in steps.values():
        step.raw_suffix = fold_key
        step.parent_timestamp = fold_key
    return rows, root, steps


def _clan_member(
    clan: str,
    *,
    status: str = "RUNNING",
    tribe: str | None = None,
    generation: str = "generation",
) -> Agent:
    member = make_transition_agent(
        cl_name=f"{clan}-member",
        agent_name=f"{clan}.worker",
        raw_suffix=f"{clan}-{generation}-member",
        status=status,
        tribe=tribe,
    )
    member.agent_clan = clan
    member.agent_clan_generation = generation
    return member


def _clan_container(agents: list[Agent], clan: str) -> Agent:
    return next(
        agent
        for agent in agents
        if agent.is_clan_container and agent.agent_clan == clan
    )


def _populate_fold_counts(app: AgentPanelCollapseApp, agents: list[Agent]) -> None:
    _, app._fold_counts = filter_agents_by_fold_state(agents, app._fold_manager)


def test_whole_panel_sweep_collapses_lanes_and_clans_banners_stay_open() -> None:
    lane_rows, lane_root, _lane_steps = _named_workflow_lane("lane")
    projected, family, _member = make_sequential_family(clan="workers")
    sibling = make_transition_agent(agent_name="sibling", tribe="research")
    agents = [*lane_rows, *projected, sibling]

    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    _populate_fold_counts(app, agents)

    lane_key = agent_fold_key(lane_root)
    family_key = agent_fold_key(family)
    clan = _clan_container(agents, "workers")
    clan_key = agent_fold_key(clan)
    assert lane_key is not None
    assert family_key is not None
    assert clan_key is not None

    app._fold_manager.expand(lane_key)
    app._fold_manager.expand(family_key)
    app._fold_manager.expand(family_key)  # -> FULLY_EXPANDED
    app._fold_manager.expand(clan_key)
    app._expanded_panel_focus = True

    app.action_collapse_panel_folds()

    registry = app._group_fold_registry.for_panel(None)
    assert app._fold_manager.get(lane_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    # `-` never collapses grouping banners, only structural lanes and clans.
    assert registry.is_collapsed(("Running",)) is False
    assert app.notifications[-1] == "Collapsed 3 folds"
    assert app.refilter_kwargs == [{"refresh_content_index": False}]
    assert app.footer_refresh_calls == 1
    # Never collapses the panel itself.
    assert None not in app._collapsed_panel_keys

    app.action_collapse_panel_folds()

    assert app._fold_manager.get(lane_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(family_key) is FoldLevel.FULLY_EXPANDED
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
    assert registry.is_collapsed(("Running",)) is False
    assert app.notifications[-1] == "Restored 3 folds"
    assert app.refilter_kwargs == [
        {"refresh_content_index": False},
        {"refresh_content_index": False},
    ]
    assert None not in app._panel_fold_sweep_records


def test_group_only_panel_reports_nothing_to_collapse_or_restore() -> None:
    alpha = make_transition_agent(cl_name="alpha", raw_suffix="alpha", status="RUNNING")
    beta = make_transition_agent(cl_name="beta", raw_suffix="beta", status="RUNNING")
    agents = [alpha, beta]

    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    _populate_fold_counts(app, agents)
    app._expanded_panel_focus = True

    app.action_collapse_panel_folds()

    registry = app._group_fold_registry.for_panel(None)
    # A panel with only an open grouping banner and no lane/clan has nothing
    # for `-` to sweep, and must not collapse the banner as a fallback.
    assert registry.is_collapsed(("Running",)) is False
    assert app.notifications == ["No folds to collapse or restore"]
    assert app.refilter_kwargs == []
    assert None not in app._panel_fold_sweep_records


def test_whole_panel_sweep_batches_clans_hidden_behind_collapsed_banner() -> None:
    running = _clan_member("hidden-running")
    done = _clan_member("visible-done", status="DONE")
    other = _clan_member("other-panel", tribe="research")
    agents = project_clan_tree([running, done, other])
    running_clan = _clan_container(agents, "hidden-running")
    done_clan = _clan_container(agents, "visible-done")
    other_clan = _clan_container(agents, "other-panel")
    running_key = agent_fold_key(running_clan)
    done_key = agent_fold_key(done_clan)
    other_key = agent_fold_key(other_clan)
    assert running_key is not None
    assert done_key is not None
    assert other_key is not None

    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    _populate_fold_counts(app, agents)
    app._fold_manager.expand(running_key)
    app._fold_manager.expand(done_key)
    app._fold_manager.expand(other_key)
    app._expanded_panel_focus = True
    registry = app._group_fold_registry.for_panel(None)
    registry.collapse(("Running",))  # hides the running clan's banner
    armed = PanelIsolationRevert(
        target_key=None, collapsed_before=frozenset({"research"})
    )
    app._panel_isolation_revert = armed

    app.action_collapse_panel_folds()

    assert app._fold_manager.get(running_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(done_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(other_key) is FoldLevel.EXPANDED
    # A `-` sweep never disarms an armed `=` isolation restore.
    assert app._panel_isolation_revert is armed
    assert app.refilter_kwargs == [{"refresh_content_index": False}]


def test_row_focus_sweep_reanchors_to_visible_lane_owner() -> None:
    rows, root, steps = _named_workflow_lane("lane")
    app = AgentPanelCollapseApp(rows)
    app._agents_with_children = list(rows)
    _populate_fold_counts(app, rows)
    lane_key = agent_fold_key(root)
    assert lane_key is not None
    app._fold_manager.expand(lane_key)

    child = steps["bash"]
    app.current_idx = rows.index(child)

    app.action_collapse_panel_folds()

    owner_idx = rows.index(root)
    assert app._fold_manager.get(lane_key) is FoldLevel.COLLAPSED
    # The lone project banner is never swept, so the lane's owner row stays
    # visible; the reanchor lands on it and focus stays on the row itself.
    assert app.current_idx == owner_idx
    registry = app._group_fold_registry.for_panel(None)
    assert registry.is_collapsed(("proj",)) is False
    assert app._current_group_key is None
    assert app._panel_selection_memory[None] == ("agent", owner_idx)
    assert app.notifications[-1] == "Collapsed 1 fold"
    assert app.refilter_kwargs == [{"refresh_content_index": False}]


def test_merged_layout_sweep_treats_merged_roster_as_one_scope() -> None:
    rows, root, _steps = _named_workflow_lane("lane", tribe="alpha")
    app = AgentPanelCollapseApp(rows, merged=True)
    app._agents_with_children = list(rows)
    _populate_fold_counts(app, rows)
    lane_key = agent_fold_key(root)
    assert lane_key is not None
    app._fold_manager.expand(lane_key)
    app.current_idx = rows.index(root)

    app.action_collapse_panel_folds()

    assert app._fold_manager.get(lane_key) is FoldLevel.COLLAPSED


def test_sibling_panel_lanes_and_equal_banner_names_are_untouched() -> None:
    default_rows, default_root, _default_steps = _named_workflow_lane("default")
    other_rows, other_root, _other_steps = _named_workflow_lane(
        "other", tribe="research"
    )
    agents = [*default_rows, *other_rows]
    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    _populate_fold_counts(app, agents)
    default_key = agent_fold_key(default_root)
    other_key = agent_fold_key(other_root)
    assert default_key is not None
    assert other_key is not None
    app._fold_manager.expand(default_key)
    app._fold_manager.expand(other_key)
    app._expanded_panel_focus = True

    app.action_collapse_panel_folds()

    default_registry = app._group_fold_registry.for_panel(None)
    other_registry = app._group_fold_registry.for_panel("research")
    assert app._fold_manager.get(default_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(other_key) is FoldLevel.EXPANDED
    # Same-named banners in both panels are never touched by the sweep.
    assert default_registry.is_collapsed(("Running",)) is False
    assert other_registry.is_collapsed(("Running",)) is False


def test_sweep_skips_ambiguous_or_malformed_clan_owners_per_candidate() -> None:
    valid_rows = project_clan_tree([_clan_member("valid")])
    malformed_rows = project_clan_tree([_clan_member("malformed")])
    duplicate_rows = project_clan_tree([_clan_member("duplicate")])
    other_duplicate_rows = project_clan_tree(
        [_clan_member("duplicate", tribe="research")]
    )
    malformed = _clan_container(malformed_rows, "malformed")
    malformed.tree_depth = 1
    agents = [
        *valid_rows,
        *malformed_rows,
        *duplicate_rows,
        *other_duplicate_rows,
    ]
    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    _populate_fold_counts(app, agents)
    valid_key = agent_fold_key(_clan_container(valid_rows, "valid"))
    malformed_key = agent_fold_key(malformed)
    duplicate_key = agent_fold_key(_clan_container(duplicate_rows, "duplicate"))
    assert valid_key is not None
    assert malformed_key is not None
    assert duplicate_key is not None
    app._fold_manager.expand(valid_key)
    app._fold_manager.expand(malformed_key)
    app._fold_manager.expand(duplicate_key)
    app._expanded_panel_focus = True

    app.action_collapse_panel_folds()

    assert app._fold_manager.get(valid_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(malformed_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(duplicate_key) is FoldLevel.EXPANDED


def test_collapsed_selected_panel_warns_without_mutating() -> None:
    rows, root, _steps = _named_workflow_lane("lane")
    app = AgentPanelCollapseApp(rows, focused_key=None)
    app._agents_with_children = list(rows)
    _populate_fold_counts(app, rows)
    lane_key = agent_fold_key(root)
    assert lane_key is not None
    app._fold_manager.expand(lane_key)
    app._collapsed_panel_keys.add(None)

    app.action_collapse_panel_folds()

    assert app._fold_manager.get(lane_key) is FoldLevel.EXPANDED
    assert app.notifications == ["Panel is collapsed"]
    assert app.refilter_kwargs == []


def test_records_are_per_panel_and_fresh_sweep_replaces_the_record() -> None:
    default_rows, default_root, _default_steps = _named_workflow_lane("default")
    other_rows, other_root, _other_steps = _named_workflow_lane(
        "other", tribe="research"
    )
    agents = [*default_rows, *other_rows]
    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    _populate_fold_counts(app, agents)
    default_key = agent_fold_key(default_root)
    other_key = agent_fold_key(other_root)
    assert default_key is not None
    assert other_key is not None
    app._fold_manager.expand(default_key)
    app._fold_manager.expand(other_key)
    app._expanded_panel_focus = True

    app.action_collapse_panel_folds()
    assert None in app._panel_fold_sweep_records
    assert "research" not in app._panel_fold_sweep_records
    first_record = app._panel_fold_sweep_records[None]

    app._panel_group.focused_idx = app._panel_group.panel_keys.index("research")
    app.action_collapse_panel_folds()
    assert "research" in app._panel_fold_sweep_records

    app._panel_group.focused_idx = app._panel_group.panel_keys.index(None)
    app._fold_manager.expand(default_key)  # hand re-expand -> collapsible again
    app.action_collapse_panel_folds()

    assert app._panel_fold_sweep_records[None] is not first_record


def test_panel_that_stops_being_live_drops_its_sweep_record() -> None:
    default_rows, _default_root, _default_steps = _named_workflow_lane("default")
    other_rows, other_root, _other_steps = _named_workflow_lane(
        "other", tribe="research"
    )
    agents = [*default_rows, *other_rows]
    app = AgentPanelCollapseApp(agents, focused_key="research")
    app._agents_with_children = list(agents)
    _populate_fold_counts(app, agents)
    other_key = agent_fold_key(other_root)
    assert other_key is not None
    app._fold_manager.expand(other_key)
    app._expanded_panel_focus = True

    app.action_collapse_panel_folds()
    assert "research" in app._panel_fold_sweep_records

    app._agents = list(default_rows)
    app._agents_with_children = list(default_rows)
    app._refresh_agents_display(list_changed=True)

    assert "research" not in app._panel_fold_sweep_records


def test_restore_liveness_filter_skips_reexpanded_and_disappeared_owners() -> None:
    rows_a, root_a, _steps_a = _named_workflow_lane("lane-a")
    _rows_b, root_b, _steps_b = _named_workflow_lane("lane-b")
    agents = [*rows_a, root_b]
    app = AgentPanelCollapseApp(agents)
    app._agents_with_children = list(agents)
    key_a = agent_fold_key(root_a)
    key_b = agent_fold_key(root_b)
    assert key_a is not None
    assert key_b is not None
    record = PanelFoldSweepRecord(
        panel_key=None,
        agent_levels=((key_a, FoldLevel.EXPANDED), (key_b, FoldLevel.EXPANDED)),
    )
    app._fold_manager.collapse_fully_all([key_a, key_b])

    # The user hand re-expands lane A; lane B's owner row disappears entirely.
    app._fold_manager.expand(key_a)
    app._agents = [a for a in app._agents if a is not root_b]
    app._agents_with_children = list(app._agents)
    app._panel_group = AgentPanelGroup.from_agents(app._agents)

    agent_levels = _live_sweep_record_entries(app, None, record)

    assert agent_levels == ()


def test_action_restore_with_nothing_left_drops_record_and_warns() -> None:
    rows, root, _steps = _named_workflow_lane("lane")
    app = AgentPanelCollapseApp(list(rows))
    app._agents_with_children = list(rows)
    _populate_fold_counts(app, rows)
    key = agent_fold_key(root)
    assert key is not None
    app._fold_manager.expand(key)
    app._expanded_panel_focus = True

    app.action_collapse_panel_folds()
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    assert None in app._panel_fold_sweep_records

    # The panel's only owner disappears before the reverse is pressed.
    app._agents = []
    app._agents_with_children = []
    app._panel_group = AgentPanelGroup.from_agents(app._agents)
    app._nav_stops_cache = None
    app._panel_index_cache = None

    app.action_collapse_panel_folds()

    assert app.notifications[-1] == "No folds to restore"
    assert None not in app._panel_fold_sweep_records


def test_sweep_tears_down_armed_panel_fold_hint_mode_first() -> None:
    rows, root, _steps = _named_workflow_lane("lane")
    app = AgentPanelCollapseApp(rows)
    app._agents_with_children = list(rows)
    _populate_fold_counts(app, rows)
    key = agent_fold_key(root)
    assert key is not None
    app._fold_manager.expand(key)
    app._expanded_panel_focus = True
    app._panel_fold_hint_mode_active = True
    teardown_calls: list[bool] = []
    app._teardown_panel_fold_hint_mode = lambda: teardown_calls.append(True)  # type: ignore[method-assign]

    app.action_collapse_panel_folds()

    assert teardown_calls == [True]
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED


def test_sweep_is_noop_outside_agents_tab() -> None:
    rows, root, _steps = _named_workflow_lane("lane")
    app = AgentPanelCollapseApp(rows)
    app._agents_with_children = list(rows)
    _populate_fold_counts(app, rows)
    key = agent_fold_key(root)
    assert key is not None
    app._fold_manager.expand(key)
    app.current_tab = "axe"

    app.action_collapse_panel_folds()

    assert app._fold_manager.get(key) is FoldLevel.EXPANDED
    assert app.notifications == []


def test_no_panel_group_warns_no_tribe_panel_to_fold() -> None:
    app = AgentPanelCollapseApp([])
    app._panel_group = None  # type: ignore[assignment]

    app.action_collapse_panel_folds()

    assert app.notifications == ["No tribe panel to fold"]

"""Tests for the ``_`` all-panel fold sweep and its per-panel reverse."""

from __future__ import annotations

from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_groups import GroupingMode
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


def _two_panel_lanes() -> tuple[list[Agent], Agent, Agent]:
    """Build two eligible tribe panels, each with one open workflow lane."""
    default_rows, default_root, _default_steps = _named_workflow_lane("default")
    other_rows, other_root, _other_steps = _named_workflow_lane(
        "other", tribe="research"
    )
    return [*default_rows, *other_rows], default_root, other_root


def test_all_panel_sweep_collapses_lanes_and_clans_in_every_panel() -> None:
    default_rows, default_root, _default_steps = _named_workflow_lane("default")
    default_clan_rows = project_clan_tree([_clan_member("default-clan")])
    other_rows, other_root, _other_steps = _named_workflow_lane(
        "other", tribe="research"
    )
    other_clan_rows = project_clan_tree([_clan_member("other-clan", tribe="research")])
    agents = [*default_rows, *default_clan_rows, *other_rows, *other_clan_rows]
    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    _populate_fold_counts(app, agents)

    default_key = agent_fold_key(default_root)
    default_clan_key = agent_fold_key(
        _clan_container(default_clan_rows, "default-clan")
    )
    other_key = agent_fold_key(other_root)
    other_clan_key = agent_fold_key(_clan_container(other_clan_rows, "other-clan"))
    assert default_key is not None
    assert default_clan_key is not None
    assert other_key is not None
    assert other_clan_key is not None

    for key in (default_key, default_clan_key, other_key, other_clan_key):
        app._fold_manager.expand(key)
    app._expanded_panel_focus = True

    app.action_collapse_all_panel_folds()

    for key in (default_key, default_clan_key, other_key, other_clan_key):
        assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    assert app.notifications[-1] == "Collapsed 4 folds in 2 panels"
    # Never collapses either panel itself.
    assert None not in app._collapsed_panel_keys
    assert "research" not in app._collapsed_panel_keys


def test_all_panel_sweep_restores_exact_levels_including_fully_expanded() -> None:
    lane_rows, lane_root, _lane_steps = _named_workflow_lane("lane")
    projected, family, _member = make_sequential_family(tribe="research")
    agents = [*lane_rows, *projected]
    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    _populate_fold_counts(app, agents)

    lane_key = agent_fold_key(lane_root)
    family_key = agent_fold_key(family)
    assert lane_key is not None
    assert family_key is not None

    app._fold_manager.expand(lane_key)
    app._fold_manager.expand(family_key)
    app._fold_manager.expand(family_key)  # -> FULLY_EXPANDED
    app._expanded_panel_focus = True

    app.action_collapse_all_panel_folds()

    assert app._fold_manager.get(lane_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED
    assert app.notifications[-1] == "Collapsed 2 folds in 2 panels"

    app.action_collapse_all_panel_folds()

    assert app._fold_manager.get(lane_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(family_key) is FoldLevel.FULLY_EXPANDED
    assert app.notifications[-1] == "Restored 2 folds in 2 panels"
    assert None not in app._panel_fold_sweep_records
    assert "research" not in app._panel_fold_sweep_records


def test_row_focus_sweep_reanchors_focused_panel_and_sweeps_others() -> None:
    default_rows, default_root, default_steps = _named_workflow_lane("default")
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

    child = default_steps["bash"]
    app.current_idx = agents.index(child)

    app.action_collapse_all_panel_folds()

    owner_idx = agents.index(default_root)
    assert app._fold_manager.get(default_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(other_key) is FoldLevel.COLLAPSED
    # The reanchor is scoped to the focused panel's own resolved fold keys.
    assert app.current_idx == owner_idx
    assert app._panel_selection_memory[None] == ("agent", owner_idx)
    assert app.notifications[-1] == "Collapsed 2 folds in 2 panels"


def test_group_banner_focus_sweeps_every_panel() -> None:
    agents, default_root, other_root = _two_panel_lanes()
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
    app._current_group_key = ("Running",)

    app.action_collapse_all_panel_folds()

    assert app._fold_manager.get(default_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(other_key) is FoldLevel.COLLAPSED


def test_whole_panel_focus_sweeps_every_panel_and_keeps_focus() -> None:
    agents, default_root, other_root = _two_panel_lanes()
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

    app.action_collapse_all_panel_folds()

    assert app._fold_manager.get(default_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(other_key) is FoldLevel.COLLAPSED
    # Whole-panel focus survives the repaint; it is never leaked or dropped.
    assert app._expanded_panel_focus is True
    assert app._panel_group.focused_key is None


def test_collapsed_focused_panel_still_sweeps_other_panels() -> None:
    agents, default_root, other_root = _two_panel_lanes()
    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    _populate_fold_counts(app, agents)
    default_key = agent_fold_key(default_root)
    other_key = agent_fold_key(other_root)
    assert default_key is not None
    assert other_key is not None
    app._fold_manager.expand(default_key)
    app._fold_manager.expand(other_key)
    app._collapsed_panel_keys.add(None)  # focused panel is effectively collapsed

    app.action_collapse_all_panel_folds()

    assert "Panel is collapsed" not in app.notifications
    assert app._fold_manager.get(other_key) is FoldLevel.COLLAPSED
    # The collapsed, focused panel is skipped even though its fold is open.
    assert app._fold_manager.get(default_key) is FoldLevel.EXPANDED
    assert app._expanded_panel_focus is False
    assert app.notifications[-1] == "Collapsed 1 fold in 1 panel"


def test_effectively_collapsed_panel_record_survives_restore_of_others() -> None:
    agents, default_root, other_root = _two_panel_lanes()
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

    app.action_collapse_all_panel_folds()
    assert None in app._panel_fold_sweep_records
    assert "research" in app._panel_fold_sweep_records

    app._collapsed_panel_keys.add(None)

    app.action_collapse_all_panel_folds()

    assert app._fold_manager.get(other_key) is FoldLevel.EXPANDED
    assert "research" not in app._panel_fold_sweep_records
    # The collapsed panel's record is untouched, not discarded.
    assert None in app._panel_fold_sweep_records
    assert app._fold_manager.get(default_key) is FoldLevel.COLLAPSED
    assert app.notifications[-1] == "Restored 1 fold in 1 panel"


def test_composes_with_single_panel_sweep_then_all_panel_sweep() -> None:
    agents, default_root, other_root = _two_panel_lanes()
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

    app.action_collapse_panel_folds()  # `-` sweeps only the focused panel.
    assert app._fold_manager.get(default_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(other_key) is FoldLevel.EXPANDED
    assert None in app._panel_fold_sweep_records
    assert "research" not in app._panel_fold_sweep_records

    app.action_collapse_all_panel_folds()  # `_` sweeps the remaining panel.
    assert app._fold_manager.get(other_key) is FoldLevel.COLLAPSED
    assert "research" in app._panel_fold_sweep_records
    assert app.notifications[-1] == "Collapsed 1 fold in 1 panel"

    app.action_collapse_all_panel_folds()  # nothing left open -> restores both.
    assert app._fold_manager.get(default_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(other_key) is FoldLevel.EXPANDED
    assert None not in app._panel_fold_sweep_records
    assert "research" not in app._panel_fold_sweep_records
    assert app.notifications[-1] == "Restored 2 folds in 2 panels"


def test_composes_with_all_panel_sweep_then_single_panel_restore() -> None:
    agents, default_root, other_root = _two_panel_lanes()
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

    app.action_collapse_all_panel_folds()  # `_` sweeps both panels.
    assert app._fold_manager.get(default_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(other_key) is FoldLevel.COLLAPSED

    app.action_collapse_panel_folds()  # `-` restores only the focused panel.
    assert app._fold_manager.get(default_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(other_key) is FoldLevel.COLLAPSED
    assert None not in app._panel_fold_sweep_records
    assert "research" in app._panel_fold_sweep_records

    # The just-restored focused panel has an open fold again, so the next `_`
    # sweeps it fresh rather than restoring the untouched "research" record.
    app.action_collapse_all_panel_folds()
    assert app._fold_manager.get(default_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(other_key) is FoldLevel.COLLAPSED
    assert None in app._panel_fold_sweep_records
    assert "research" in app._panel_fold_sweep_records
    assert app.notifications[-1] == "Collapsed 1 fold in 1 panel"

    app.action_collapse_all_panel_folds()  # nothing left open -> restores both.
    assert app._fold_manager.get(default_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(other_key) is FoldLevel.EXPANDED
    assert None not in app._panel_fold_sweep_records
    assert "research" not in app._panel_fold_sweep_records
    assert app.notifications[-1] == "Restored 2 folds in 2 panels"


def test_merged_layout_treats_merged_roster_as_one_scope() -> None:
    rows, root, _steps = _named_workflow_lane("lane", tribe="alpha")
    app = AgentPanelCollapseApp(rows, merged=True)
    app._agents_with_children = list(rows)
    _populate_fold_counts(app, rows)
    lane_key = agent_fold_key(root)
    assert lane_key is not None
    app._fold_manager.expand(lane_key)
    app.current_idx = rows.index(root)

    app.action_collapse_all_panel_folds()

    assert app._fold_manager.get(lane_key) is FoldLevel.COLLAPSED
    assert app.notifications[-1] == "Collapsed 1 fold in 1 panel"

    app.action_collapse_all_panel_folds()

    assert app._fold_manager.get(lane_key) is FoldLevel.EXPANDED
    assert app.notifications[-1] == "Restored 1 fold in 1 panel"


def test_no_panel_group_warns_no_tribe_panel_to_fold() -> None:
    app = AgentPanelCollapseApp([])
    app._panel_group = None  # type: ignore[assignment]

    app.action_collapse_all_panel_folds()

    assert app.notifications == ["No tribe panel to fold"]


def test_all_panels_collapsed_warns() -> None:
    agents, _default_root, _other_root = _two_panel_lanes()
    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    _populate_fold_counts(app, agents)
    app._collapsed_panel_keys.update({None, "research"})

    app.action_collapse_all_panel_folds()

    assert app.notifications == ["All tribe panels are collapsed"]


def test_nothing_to_collapse_or_restore_warns() -> None:
    alpha = make_transition_agent(cl_name="alpha", raw_suffix="alpha", status="RUNNING")
    beta = make_transition_agent(
        cl_name="beta", raw_suffix="beta", status="RUNNING", tribe="research"
    )
    agents = [alpha, beta]
    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    _populate_fold_counts(app, agents)
    app._expanded_panel_focus = True

    app.action_collapse_all_panel_folds()

    assert app.notifications == ["No folds to collapse or restore"]


def test_notification_grammar_for_folds_and_panels() -> None:
    lane_rows, lane_root, _lane_steps = _named_workflow_lane("lane")
    clan_rows = project_clan_tree([_clan_member("workers")])
    other_rows, _other_root, _other_steps = _named_workflow_lane(
        "other", tribe="research"
    )
    agents = [*lane_rows, *clan_rows, *other_rows]
    app = AgentPanelCollapseApp(agents, focused_key=None)
    app._agents_with_children = list(agents)
    _populate_fold_counts(app, agents)
    lane_key = agent_fold_key(lane_root)
    clan_key = agent_fold_key(_clan_container(clan_rows, "workers"))
    assert lane_key is not None
    assert clan_key is not None
    app._fold_manager.expand(lane_key)
    app._fold_manager.expand(clan_key)
    app._expanded_panel_focus = True
    # The "research" panel has nothing open, so only one panel contributes.

    app.action_collapse_all_panel_folds()

    assert app.notifications[-1] == "Collapsed 2 folds in 1 panel"

    app.action_collapse_all_panel_folds()

    assert app.notifications[-1] == "Restored 2 folds in 1 panel"


def test_restore_marked_keys_names_every_swept_panel_after_all_panel_sweep() -> None:
    agents, default_root, other_root = _two_panel_lanes()
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

    app.action_collapse_all_panel_folds()

    assert app._panel_fold_restore_marked_keys() == {
        None: frozenset({default_key}),
        "research": frozenset({other_key}),
    }


def test_fold_manager_mutation_called_once_per_press() -> None:
    agents, default_root, other_root = _two_panel_lanes()
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

    collapse_calls: list[list[str]] = []
    original_collapse = app._fold_manager.collapse_fully_all

    def counting_collapse(keys: list[str]) -> bool:
        collapse_calls.append(list(keys))
        return original_collapse(keys)

    app._fold_manager.collapse_fully_all = counting_collapse  # type: ignore[method-assign]

    app.action_collapse_all_panel_folds()

    assert len(collapse_calls) == 1
    assert set(collapse_calls[0]) == {default_key, other_key}
    assert app.refilter_kwargs == [{"refresh_content_index": False}]
    assert app.footer_refresh_calls == 1

    restore_calls: list[dict[str, FoldLevel]] = []
    original_restore = app._fold_manager.restore_levels

    def counting_restore(levels: dict[str, FoldLevel]) -> bool:
        restore_calls.append(dict(levels))
        return original_restore(levels)

    app._fold_manager.restore_levels = counting_restore  # type: ignore[method-assign]

    app.action_collapse_all_panel_folds()

    assert len(restore_calls) == 1
    assert restore_calls[0] == {
        default_key: FoldLevel.EXPANDED,
        other_key: FoldLevel.EXPANDED,
    }
    assert app.refilter_kwargs == [
        {"refresh_content_index": False},
        {"refresh_content_index": False},
    ]
    assert app.footer_refresh_calls == 2

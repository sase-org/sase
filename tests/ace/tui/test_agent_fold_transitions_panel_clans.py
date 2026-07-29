"""Selected-panel clan rung coverage for the uppercase-H ladder."""

from __future__ import annotations

from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup, PanelIsolationRevert
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


def _clan_container(agents: list[Agent], clan: str) -> Agent:
    return next(
        agent
        for agent in agents
        if agent.is_clan_container and agent.agent_clan == clan
    )


def test_selected_panel_h_collapses_lanes_before_clans_before_group() -> None:
    projected, family, _member = make_sequential_family(clan="workers")
    sibling = make_agent(agent_name="sibling", tribe="research")
    agents = [*projected, sibling]
    clan = _clan_container(agents, "workers")
    family_key = agent_fold_key(family)
    clan_key = agent_fold_key(clan)
    assert family_key is not None and clan_key is not None

    app = StubFoldApp(agents, current_idx=agents.index(clan))
    app._agents_with_children = list(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._fold_manager.expand(family_key)
    app._fold_manager.expand(family_key)
    app._fold_manager.expand(clan_key)
    app._expanded_panel_focus = True

    app.action_hooks_or_collapse_all()

    registry = app._group_fold_registry.for_panel(None)
    assert app._fold_manager.get(family_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
    assert not registry.is_collapsed(("Running",))

    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
    assert not registry.is_collapsed(("Running",))

    app.action_hooks_or_collapse_all()

    assert registry.is_collapsed(("Running",))
    assert app.refilter_calls == 3
    assert app.refilter_kwargs == [
        {"prior_pos": None, "refresh_content_index": False},
        {"prior_pos": None, "refresh_content_index": False},
        {"prior_pos": None, "refresh_content_index": False},
    ]


def test_selected_panel_clan_rung_batches_hidden_clans_and_preserves_state() -> None:
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
    assert running_key is not None and done_key is not None and other_key is not None

    app = StubFoldApp(agents, current_idx=agents.index(done_clan))
    app._agents_with_children = list(agents)
    app._grouping_mode = GroupingMode.BY_STATUS
    app._fold_manager.expand(running_key)
    app._fold_manager.expand(done_key)
    app._fold_manager.expand(other_key)
    app._expanded_panel_focus = True
    remembered = ("agent", app.current_idx)
    app._panel_selection_memory[None] = remembered
    selected_idx = app.current_idx
    selected_registry = app._group_fold_registry.for_panel(None)
    sibling_registry = app._group_fold_registry.for_panel("research")
    selected_registry.collapse(("Running",))
    selected_registry.collapse(("Done", "nested"))
    sibling_registry.collapse(("Running", "other"))
    selected_snapshot = selected_registry.snapshot()
    sibling_snapshot = sibling_registry.snapshot()
    armed = PanelIsolationRevert(
        target_key=None,
        collapsed_before=frozenset({"research"}),
    )
    app._panel_isolation_revert = armed

    target = app._resolve_focused_panel_clan_collapse_target()
    assert target is not None
    assert target.fold_keys == (running_key, done_key)

    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(running_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(done_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(other_key) is FoldLevel.EXPANDED
    assert selected_registry.snapshot() == selected_snapshot
    assert sibling_registry.snapshot() == sibling_snapshot
    assert app.current_idx == selected_idx
    assert app._panel_selection_memory[None] == remembered
    assert app._expanded_panel_focus is True
    assert app._current_group_key is None
    assert app._panel_isolation_revert is armed
    assert app.refilter_calls == 1
    assert app.refilter_kwargs == [{"prior_pos": None, "refresh_content_index": False}]
    assert app.group_fold_changes == []


def test_selected_panel_clan_probe_fails_closed_per_candidate() -> None:
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
    valid_key = agent_fold_key(_clan_container(valid_rows, "valid"))
    malformed_key = agent_fold_key(malformed)
    duplicate_key = agent_fold_key(_clan_container(duplicate_rows, "duplicate"))
    assert (
        valid_key is not None
        and malformed_key is not None
        and duplicate_key is not None
    )

    app = StubFoldApp(agents)
    app._agents_with_children = list(agents)
    app._fold_manager.expand(valid_key)
    app._fold_manager.expand(malformed_key)
    app._fold_manager.expand(duplicate_key)
    app._panel_group = AgentPanelGroup.from_agents(app._agents)
    app._expanded_panel_focus = True

    target = app._resolve_focused_panel_clan_collapse_target()
    assert target is not None
    assert target.fold_keys == (valid_key,)

    app.action_hooks_or_collapse_all()

    assert app._fold_manager.get(valid_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(malformed_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(duplicate_key) is FoldLevel.EXPANDED


def test_panel_clan_rung_is_unavailable_outside_expanded_split_panel_focus() -> None:
    agents = project_clan_tree([_clan_member("workers")])
    clan_key = agent_fold_key(_clan_container(agents, "workers"))
    assert clan_key is not None

    row_focused = StubFoldApp(agents)
    row_focused._fold_manager.expand(clan_key)
    assert row_focused._resolve_focused_panel_clan_collapse_target() is None

    collapsed = StubFoldApp(agents)
    collapsed._fold_manager.expand(clan_key)
    collapsed._collapsed_panel_keys.add(None)
    assert collapsed._resolve_focused_panel_clan_collapse_target() is None

    merged = StubFoldApp(agents)
    merged._fold_manager.expand(clan_key)
    merged._agent_panels_grouped = True
    merged._expanded_panel_focus = True
    assert merged._resolve_focused_panel_clan_collapse_target() is None

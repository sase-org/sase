"""Tests for selecting and revealing agent neighbor navigation targets."""

from __future__ import annotations

from sase.ace.tui.modals import AgentNeighborModal
from sase.ace.tui.models import filter_agents_by_fold_state
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldLevel

from ._agent_neighbor_navigation_helpers import NeighborApp, make_agent


def _fold_clans(
    complete: list[Agent],
    origin: Agent,
    *,
    collapsed_panel_keys: set[str | None] | None = None,
) -> NeighborApp:
    """Build the navigation harness from the real folded clan projection."""
    app = NeighborApp(
        complete,
        collapsed_panel_keys=collapsed_panel_keys,
    )
    app._agents, app._fold_counts = filter_agents_by_fold_state(
        complete,
        app._fold_manager,
    )
    app._panel_group = AgentPanelGroup.from_agents(
        app._agents,
        collapsed_panel_keys=app._collapsed_panel_keys,
    )
    app.current_idx = next(
        idx
        for idx, agent in enumerate(app._agents)
        if agent.identity == origin.identity
    )
    app._invalidate_agent_panel_cache()
    return app


def _clan_member(
    name: str,
    *,
    clan: str,
    generation: str,
    tribe: str | None = None,
) -> Agent:
    member = make_agent(name, tribe=tribe, status="DONE")
    member.agent_clan = clan
    member.agent_clan_generation = generation
    return member


def test_agent_neighbor_navigation_selecting_visible_descendant_jumps() -> None:
    agents = [make_agent("foo"), make_agent("foo.bar"), make_agent("foo.baz")]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()

    app.pushed_callbacks[0](0)

    assert app.current_idx == 1
    assert app.acknowledged == [agents[1]]


def test_agent_neighbor_navigation_selecting_dismissed_descendant_revives() -> None:
    visible = [make_agent("foo.bar")]
    dismissed = make_agent("foo.bar.dismissed", status="DONE")
    app = NeighborApp(visible)
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
    visible = [make_agent("fam--plan")]
    dismissed = make_agent("fam--plan--dismissed", status="DONE")
    app = NeighborApp(visible)
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
        make_agent("foo.plan"),
        make_agent("foo.code", tribe="review"),
    ]
    app = NeighborApp(agents)
    assert app._panel_group.panel_keys == [None, "review"]

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert app.focused_panel_refreshes == [0]
    assert app.highlight_refreshes == 0


def test_agent_neighbor_navigation_excludes_collapsed_hidden_rows() -> None:
    agents = [
        make_agent("foo.code"),
        make_agent("foo.plan"),
        make_agent("foo.plan.review"),
    ]
    app = NeighborApp(
        agents,
        current_idx=0,
        collapsed=[("proj", "demo", "foo", "foo.plan")],
    )

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app.acknowledged == []


def test_agent_neighbor_navigation_guard_blocks_row_change() -> None:
    agents = [make_agent("foo.plan"), make_agent("foo.code")]
    app = NeighborApp(agents)
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
    origin = make_agent("foo.plan")
    target = make_agent("foo.code", tribe="alpha", status="DONE")
    unrelated = make_agent("unrelated.agent", tribe="zeta")
    app = NeighborApp(
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


def test_agent_neighbor_modal_resolves_stale_numeric_index_by_identity() -> None:
    origin = make_agent("foo.plan")
    target = make_agent("foo.code", tribe="alpha")
    other = make_agent("foo.review", tribe="zeta")
    app = NeighborApp(
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
    origin = make_agent("foo.plan")
    target = make_agent("foo.code", tribe="alpha")
    other = make_agent("foo.review", tribe="zeta")
    app = NeighborApp(
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
    origin = make_agent("foo.plan")
    target_parent = make_agent("target-container")
    target_parent.agent_clan = "target-clan"
    target = make_agent("foo.code")
    target.parent_timestamp = target_parent.raw_suffix

    other_parent = make_agent("other-container")
    other_parent.agent_clan = "other-clan"
    other_child = make_agent("unrelated.child")
    other_child.parent_timestamp = other_parent.raw_suffix
    complete = project_clan_tree(
        [other_parent, other_child, origin, target_parent, target]
    )
    origin_idx = next(
        idx for idx, agent in enumerate(complete) if agent.identity == origin.identity
    )
    app = NeighborApp(complete, current_idx=origin_idx)
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


def test_folded_clan_sole_neighbor_is_counted_and_direct_jumped() -> None:
    origin = make_agent("foo.plan")
    target = _clan_member(
        "foo.code",
        clan="workers",
        generation="one",
        tribe="alpha",
    )
    complete = project_clan_tree([origin, target])
    app = _fold_clans(complete, origin)
    target_container = next(agent for agent in complete if agent.is_clan_container)
    target_fold_key = agent_fold_key(target_container)
    assert target_fold_key is not None

    assert app._selected_agent_neighbor_count(origin) == 1
    app.action_start_sibling_mode()

    assert app.pushed_screens == []
    assert app._agents[app.current_idx].identity == target.identity
    assert app._fold_manager.get(target_fold_key) is FoldLevel.EXPANDED
    assert app.refilter_calls == 1
    assert app.display_refreshes == [{"list_changed": True, "defer_detail": True}]


def test_multiple_folded_clan_neighbors_appear_in_chooser() -> None:
    origin = make_agent("foo.plan")
    alpha = _clan_member(
        "foo.code",
        clan="alpha-workers",
        generation="one",
        tribe="alpha",
    )
    beta = _clan_member(
        "foo.review",
        clan="beta-workers",
        generation="one",
        tribe="beta",
    )
    complete = project_clan_tree([origin, beta, alpha])
    app = _fold_clans(complete, origin)

    app.action_start_sibling_mode()

    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [choice.agent_name for choice in modal._choices] == [
        "foo.code",
        "foo.review",
    ]
    assert [choice.panel_label for choice in modal._choices] == ["@alpha", "@beta"]
    assert [choice.global_idx for choice in modal._choices] == [None, None]

    app.pushed_callbacks[0](1)

    assert app._agents[app.current_idx].identity == beta.identity
    containers = {
        agent.agent_clan: agent for agent in complete if agent.is_clan_container
    }
    alpha_key = agent_fold_key(containers["alpha-workers"])
    beta_key = agent_fold_key(containers["beta-workers"])
    assert alpha_key is not None and beta_key is not None
    assert app._fold_manager.get(alpha_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(beta_key) is FoldLevel.EXPANDED


def test_folded_clan_neighbor_reveals_exact_clan_and_collapsed_tribe() -> None:
    origin = make_agent("foo.plan")
    target = _clan_member(
        "foo.code",
        clan="workers",
        generation="new",
        tribe="alpha",
    )
    other_generation = _clan_member(
        "foo.review",
        clan="workers",
        generation="old",
        tribe="beta",
    )
    unrelated = _clan_member(
        "bar.code",
        clan="other",
        generation="one",
        tribe="zeta",
    )
    complete = project_clan_tree([origin, unrelated, other_generation, target])
    app = _fold_clans(
        complete,
        origin,
        collapsed_panel_keys={"alpha", "beta", "zeta"},
    )

    app.action_start_sibling_mode()
    modal = app.pushed_screens[0]
    target_choice = next(
        idx
        for idx, choice in enumerate(modal._choices)
        if choice.agent_name == target.agent_name
    )
    assert modal._choices[target_choice].panel_label == "@alpha"
    app.pushed_callbacks[0](target_choice)

    containers = {
        (agent.agent_clan, agent.agent_clan_generation): agent
        for agent in complete
        if agent.is_clan_container
    }
    target_key = agent_fold_key(containers[("workers", "new")])
    old_key = agent_fold_key(containers[("workers", "old")])
    unrelated_key = agent_fold_key(containers[("other", "one")])
    assert target_key is not None and old_key is not None and unrelated_key is not None
    assert app._fold_manager.get(target_key) is FoldLevel.EXPANDED
    assert app._fold_manager.get(old_key) is FoldLevel.COLLAPSED
    assert app._fold_manager.get(unrelated_key) is FoldLevel.COLLAPSED
    assert app._agents[app.current_idx].identity == target.identity
    assert app._panel_group.focused_key == "alpha"
    assert app._collapsed_panel_keys == {"beta", "zeta"}
    assert app.panel_fold_changes == [("alpha", False)]
    assert app.refilter_calls == 1
    assert app.display_refreshes == [{"list_changed": True, "defer_detail": True}]


def test_folded_clan_neighbor_respects_active_search() -> None:
    origin = make_agent("foo.plan")
    target = _clan_member(
        "foo.code",
        clan="workers",
        generation="one",
    )
    app = _fold_clans(project_clan_tree([origin, target]), origin)
    app._agent_search_query = "name:foo.plan"

    assert app._selected_agent_neighbor_count(origin) == 0
    app.action_start_sibling_mode()

    assert app.pushed_screens == []
    assert app._agents[app.current_idx].identity == origin.identity
    assert app.refilter_calls == 0


def test_folded_clan_neighbor_excludes_starting_and_dismissed_members() -> None:
    origin = make_agent("foo.plan")
    starting = _clan_member(
        "foo.starting",
        clan="workers",
        generation="one",
    )
    starting.status = "STARTING"
    dismissed = _clan_member(
        "foo.dismissed",
        clan="reviewers",
        generation="one",
    )
    complete = project_clan_tree([origin, starting, dismissed])
    app = _fold_clans(complete, origin)
    app._dismissed_agents.add(dismissed.identity)

    assert app._selected_agent_neighbor_count(origin) == 0
    app.action_start_sibling_mode()

    assert app.pushed_screens == []
    assert app.refilter_calls == 0


def test_folded_clan_neighbor_excludes_inner_family_member() -> None:
    origin = make_agent("foo.other")
    family = _clan_member(
        "foo.family--plan",
        clan="workers",
        generation="one",
    )
    family.agent_family = "foo.family"
    child = make_agent("foo.family--code", status="DONE")
    child.agent_family = "foo.family"
    child.parent_timestamp = family.raw_suffix
    family.runtime_children = [child]
    complete = project_clan_tree([origin, family, child])
    app = _fold_clans(complete, origin)

    index = app._agent_neighbor_index()
    identities = {
        target.identity for target in index.neighbor_targets_for(origin.identity)
    }

    assert family.identity in identities
    assert child.identity not in identities


def test_folded_clan_neighbor_includes_expanded_inner_family_member() -> None:
    origin = make_agent("foo.other")
    family = _clan_member(
        "foo.family--plan",
        clan="workers",
        generation="one",
    )
    family.agent_family = "foo.family"
    child = make_agent("foo.family--code", status="DONE")
    child.agent_family = "foo.family"
    child.parent_timestamp = family.raw_suffix
    family.runtime_children = [child]
    complete = project_clan_tree([origin, family, child])
    app = _fold_clans(complete, origin)
    assert family.raw_suffix is not None
    app._fold_manager.expand(family.raw_suffix)

    identities = {
        target.identity
        for target in app._agent_neighbor_index().neighbor_targets_for(origin.identity)
    }

    assert family.identity in identities
    assert child.identity in identities


def test_folded_clan_modal_stale_target_cancels_without_expansion() -> None:
    origin = make_agent("foo.plan")
    target = _clan_member(
        "foo.code",
        clan="workers",
        generation="one",
    )
    peer = _clan_member(
        "foo.review",
        clan="reviewers",
        generation="one",
    )
    complete = project_clan_tree([origin, target, peer])
    app = _fold_clans(complete, origin)
    app.action_start_sibling_mode()
    modal = app.pushed_screens[0]
    target_choice = next(
        idx
        for idx, choice in enumerate(modal._choices)
        if choice.agent_name == target.agent_name
    )
    app._agents_with_children = [
        agent for agent in complete if agent.identity != target.identity
    ]
    app.pushed_callbacks[0](target_choice)

    assert app._agents[app.current_idx].identity == origin.identity
    assert app.refilter_calls == 0
    assert app.display_refreshes == []
    assert all(
        app._fold_manager.get(agent_fold_key(container) or "") is FoldLevel.COLLAPSED
        for container in complete
        if container.is_clan_container
    )

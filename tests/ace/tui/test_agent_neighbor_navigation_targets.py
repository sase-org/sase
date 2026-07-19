"""Tests for selecting and revealing agent neighbor navigation targets."""

from __future__ import annotations

from sase.ace.tui.modals import AgentNeighborModal
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldLevel

from ._agent_neighbor_navigation_helpers import NeighborApp, make_agent


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
        make_agent("foo.code", tag="review"),
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
    target = make_agent("foo.code", tag="alpha", status="DONE")
    unrelated = make_agent("unrelated.agent", tag="zeta")
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
    target = make_agent("foo.code", tag="alpha")
    other = make_agent("foo.review", tag="zeta")
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
    target = make_agent("foo.code", tag="alpha")
    other = make_agent("foo.review", tag="zeta")
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

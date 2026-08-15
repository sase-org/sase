"""Digit-key jumps that address lane neighbors rather than family members."""

from __future__ import annotations

from ._member_jump_navigation_helpers import (
    JumpHarness,
    make_agent,
    make_family,
    make_role_jump_map,
)


def test_single_sase_agent_digit_jumps_to_numbered_neighbor() -> None:
    container = make_agent("foo.plan")
    neighbor = make_agent("foo.code")
    app = JumpHarness([container, neighbor], container)
    app._neighbor_targets[container.identity] = {neighbor.identity}
    app._member_jump_maps[container.identity] = make_role_jump_map(
        container,
        [(neighbor, "neighbor")],
    )

    assert app._handle_member_jump_key("0") is True

    assert app._agents[app.current_idx].identity == neighbor.identity
    assert app.notifications == []


def test_family_lane_digit_ladder_addresses_members_then_neighbors() -> None:
    complete, root, child = make_family(in_clan=False)
    neighbor = make_agent("alpha.peer")
    complete.append(neighbor)
    app = JumpHarness(complete, root)
    app._neighbor_targets[root.identity] = {neighbor.identity}
    app._member_jump_maps[root.identity] = make_role_jump_map(
        root,
        [(child, "member"), (neighbor, "neighbor")],
    )

    assert app._handle_member_jump_key("0") is True
    assert app._agents[app.current_idx].identity == child.identity

    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == root.identity
    )
    assert app._handle_member_jump_key("1") is True
    assert app._agents[app.current_idx].identity == neighbor.identity


def test_dismissed_neighbor_digit_revives_instead_of_jumping() -> None:
    container = make_agent("foo")
    dismissed = make_agent("foo.scratch")
    app = JumpHarness([container], container)
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    app._member_jump_maps[container.identity] = make_role_jump_map(
        container,
        [(dismissed, "dismissed")],
    )

    assert app._handle_member_jump_key("0") is True

    assert app.revived_agents == [dismissed]
    assert app._agents[app.current_idx].identity == container.identity


def test_stale_neighbor_digit_uses_neighbor_specific_cancellation() -> None:
    container = make_agent("foo.plan")
    neighbor = make_agent("foo.code")
    app = JumpHarness([container, neighbor], container)
    app._member_jump_maps[container.identity] = make_role_jump_map(
        container,
        [(neighbor, "neighbor")],
    )

    assert app._handle_member_jump_key("0") is True

    assert app._agents[app.current_idx].identity == container.identity
    assert app.notifications == ["Neighbor list changed; jump cancelled"]


def test_digits_do_nothing_on_rows_that_do_not_own_lanes() -> None:
    root = make_agent("alpha--plan", family="alpha", role="plan")
    workflow_step = make_agent("workflow.step")
    workflow_step.parent_timestamp = root.raw_suffix
    workflow_step.parent_workflow = "demo-workflow"
    workflow_step.step_type = "agent"
    app = JumpHarness([root, workflow_step], root)
    app._fold_manager.expand(root.raw_suffix or "")
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == workflow_step.identity
    )
    assert app._handle_member_jump_key("0") is False

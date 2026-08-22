"""Digit jumps issued from a selected family member row rather than its container."""

from __future__ import annotations

from sase.ace.tui.models.agent import Agent

from ._member_jump_navigation_helpers import (
    JumpHarness,
    make_agent,
    make_family,
    make_jump_map,
    make_large_family,
    select_member,
)


def test_selected_family_member_digit_jumps_to_sibling() -> None:
    complete, root, child = make_family(in_clan=False)
    app = JumpHarness(complete, root)
    select_member(app, root, child)
    app._member_jump_maps[child.identity] = make_jump_map(child, [root])

    assert app._handle_member_jump_key("0") is True

    assert app._agents[app.current_idx].identity == root.identity
    assert app.notifications == []


def test_family_member_jump_to_self_is_rejected_as_stale() -> None:
    complete, root, child = make_family(in_clan=False)
    app = JumpHarness(complete, root)
    select_member(app, root, child)
    app._member_jump_maps[child.identity] = make_jump_map(child, [child])

    assert app._handle_member_jump_key("0") is True

    assert app._agents[app.current_idx].identity == child.identity
    assert app.notifications[-1] == "Shell roster changed; jump cancelled"


def test_family_member_jump_target_no_longer_in_family_cancels_as_stale() -> None:
    complete, root, child = make_family(in_clan=False)
    stranger = make_agent("stranger")
    complete.append(stranger)
    app = JumpHarness(complete, root)
    select_member(app, root, child)
    app._member_jump_maps[child.identity] = make_jump_map(child, [stranger])

    assert app._handle_member_jump_key("0") is True

    assert app._agents[app.current_idx].identity == child.identity
    assert app.notifications[-1] == "Shell roster changed; jump cancelled"


def test_two_digit_family_member_buffers_against_own_container_identity() -> None:
    complete, root, children = make_large_family(12)
    selected = children[5]
    others = [root, *[member for member in children if member is not selected]]
    app = JumpHarness(complete, root)
    select_member(app, root, selected)
    app._member_jump_maps[selected.identity] = make_jump_map(selected, others)

    assert app._handle_member_jump_key("1") is True
    assert app._member_jump_pending_digit == "1"
    assert app._member_jump_pending_container_identity == selected.identity
    assert app.footer_digits == ["1"]

    assert app._handle_member_jump_key("0") is True

    assert app._agents[app.current_idx].identity == others[10].identity


def _family_with_nested_monitor() -> tuple[list[Agent], Agent, Agent, Agent]:
    from sase.ace.tui.models._agent_tree import project_clan_tree

    complete, root, child = make_family(in_clan=False)
    monitor = make_agent("alpha--mon", family="alpha", role="monitor")
    monitor.monitor_id = "m-jump"
    monitor.monitor_state = "completed"
    monitor.parent_timestamp = child.raw_suffix
    child.runtime_children = [monitor]
    child.followup_agents = [monitor]
    projected = project_clan_tree([*complete, monitor])
    projected_root = next(
        agent for agent in projected if agent.identity == root.identity
    )
    projected_child = next(
        agent for agent in projected if agent.identity == child.identity
    )
    projected_monitor = next(
        agent for agent in projected if agent.identity == monitor.identity
    )
    projected_child.family_container = projected_root
    projected_monitor.family_container = projected_root
    return projected, projected_root, projected_child, projected_monitor


def test_family_container_digit_jumps_to_nested_monitor() -> None:
    complete, root, child, monitor = _family_with_nested_monitor()
    app = JumpHarness(complete, root)
    app._fold_manager.expand(root.raw_suffix or "")
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == root.identity
    )
    app._member_jump_maps[root.identity] = make_jump_map(root, [root, child, monitor])

    assert app._handle_member_jump_key("2") is True

    assert app._agents[app.current_idx].identity == monitor.identity
    assert app.notifications == []


def test_selected_family_shell_digit_jumps_to_nested_monitor_sibling() -> None:
    complete, root, child, monitor = _family_with_nested_monitor()
    app = JumpHarness(complete, root)
    select_member(app, root, child)
    app._member_jump_maps[child.identity] = make_jump_map(child, [root, monitor])

    assert app._handle_member_jump_key("1") is True

    assert app._agents[app.current_idx].identity == monitor.identity
    assert app.notifications == []


def test_family_missing_digit_uses_shell_language() -> None:
    complete, root, child = make_family(in_clan=False)
    app = JumpHarness(complete, root)
    app._member_jump_maps[root.identity] = make_jump_map(root, [root, child])

    assert app._handle_member_jump_key("8") is True

    assert app._agents[app.current_idx].identity == root.identity
    assert app.notifications[-1] == "No shell 8"

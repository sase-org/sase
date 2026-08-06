"""Digit-key navigation for numbered clan and family member rosters."""

from __future__ import annotations

from typing import Any, cast

import pytest

from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.fold_state import FoldLevel

from ._member_jump_navigation_helpers import (
    JumpHarness,
    KeyEvent,
    PendingKeyboardHarness,
    make_agent,
    make_clan,
    make_family,
    make_jump_map,
)


def test_single_digit_reveals_collapsed_clan_and_back_restores_container() -> None:
    complete, container = make_clan(3)
    members = list(container.runtime_children)
    app = JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = make_jump_map(container, members)
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    assert app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED

    assert app._handle_member_jump_key("1") is True

    assert app._agents[app.current_idx].identity == members[1].identity
    assert app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
    assert len(app._entry_jump_agents_anchor_stack) == 1
    assert app.refilter_calls == 1
    assert app.display_refreshes == [True]

    assert app._restore_agents_jump_anchor() is True
    assert app._agents[app.current_idx].identity == container.identity


@pytest.mark.parametrize("in_clan", [False, True])
def test_family_member_jump_reveals_standalone_and_nested_chains(
    in_clan: bool,
) -> None:
    complete, root, child = make_family(in_clan=in_clan)
    app = JumpHarness(complete, complete[0] if in_clan else root)
    if in_clan:
        clan_container = complete[0]
        clan_key = agent_fold_key(clan_container)
        assert clan_key is not None
        app._fold_manager.expand(clan_key)
        app._refilter_agents()
        app.current_idx = next(
            index
            for index, agent in enumerate(app._agents)
            if agent.identity == root.identity
        )
    app._member_jump_maps[root.identity] = make_jump_map(root, [root, child])

    assert app._handle_member_jump_key("1") is True

    assert app._agents[app.current_idx].identity == child.identity
    assert app._fold_manager.get(root.raw_suffix or "") is FoldLevel.EXPANDED


def test_family_member_jump_accepts_concrete_workflow_planner_target() -> None:
    root = make_agent("alpha--plan", family="alpha", role="plan")
    planner = make_agent("alpha--plan-step", family="alpha", role="plan")
    planner.plan_chain_root = False
    planner.parent_timestamp = root.raw_suffix
    planner.parent_workflow = "ace-run"
    planner.step_type = "agent"
    coder = make_agent("alpha--code", family="alpha", role="code")
    coder.parent_timestamp = root.raw_suffix
    root.runtime_children = [planner, coder]
    root.followup_agents = [coder]
    complete = [root, planner, coder]
    app = JumpHarness(complete, root)
    app._member_jump_maps[root.identity] = make_jump_map(root, [planner, coder])

    assert app._handle_member_jump_key("0") is True

    assert app.notifications == []
    assert app._agents[app.current_idx].identity == planner.identity
    assert app._fold_manager.get(root.raw_suffix or "") is FoldLevel.EXPANDED


def test_two_digit_buffer_completion_escape_and_other_key_cancellation() -> None:
    complete, container = make_clan(11)
    members = list(container.runtime_children)
    app = JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = make_jump_map(container, members)

    assert app._handle_member_jump_key("1") is True
    assert app._member_jump_pending_digit == "1"
    assert app.footer_digits == ["1"]
    assert app._handle_member_jump_key("0") is True
    assert app._member_jump_pending_digit is None
    assert app._agents[app.current_idx].identity == members[10].identity

    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )
    assert app._handle_member_jump_key("0") is True
    assert app._handle_member_jump_key("escape") is True
    assert app._member_jump_pending_digit is None

    assert app._handle_member_jump_key("0") is True
    assert app._handle_member_jump_key("j") is False
    assert app._member_jump_pending_digit is None


def test_pending_other_key_is_cancelled_then_processed_normally() -> None:
    app = PendingKeyboardHarness()
    event = KeyEvent("j", "j")

    app.on_key(cast(Any, event))

    assert app._member_jump_pending_digit is None
    assert app.footer_refreshes == 1
    assert event.prevented is False
    assert event.stopped is False


def test_stale_map_and_missing_digit_cancel_without_moving() -> None:
    complete, container = make_clan(2)
    members = list(container.runtime_children)
    app = JumpHarness(complete, container)
    app._member_jump_maps[container.identity] = make_jump_map(container, members)
    original_idx = app.current_idx

    container.runtime_children.remove(members[1])
    assert app._handle_member_jump_key("1") is True
    assert app.current_idx == original_idx
    assert app.notifications[-1] == "Member roster changed; jump cancelled"

    assert app._handle_member_jump_key("8") is True
    assert app.current_idx == original_idx
    assert app.notifications[-1] == "No member 8"

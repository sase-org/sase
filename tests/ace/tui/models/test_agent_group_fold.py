"""Tests for the group-fold state model."""

from __future__ import annotations

from sase.ace.tui.models.agent_group_fold import (
    GROUP_LEVEL_MAX,
    GROUP_LEVEL_MIN,
    AgentGroupFoldState,
)


def test_default_state_is_fully_expanded() -> None:
    state = AgentGroupFoldState()
    assert state.level == GROUP_LEVEL_MAX == 2


def test_collapse_steps_down_one_level_per_call() -> None:
    state = AgentGroupFoldState()
    levels = []
    while state.collapse():
        levels.append(state.level)
    assert levels == [1, 0]
    # Already at floor: no further change.
    assert state.collapse() is False
    assert state.level == GROUP_LEVEL_MIN


def test_expand_steps_up_one_level_per_call() -> None:
    state = AgentGroupFoldState(level=0)
    levels = []
    while state.expand():
        levels.append(state.level)
    assert levels == [1, 2]
    # Already at ceiling: no further change.
    assert state.expand() is False
    assert state.level == GROUP_LEVEL_MAX


def test_expand_all_jumps_to_max() -> None:
    state = AgentGroupFoldState(level=0)
    assert state.expand_all() is True
    assert state.level == GROUP_LEVEL_MAX
    # No-op when already at max.
    assert state.expand_all() is False


def test_collapse_all_jumps_to_min() -> None:
    state = AgentGroupFoldState(level=2)
    assert state.collapse_all() is True
    assert state.level == GROUP_LEVEL_MIN
    # No-op when already at min.
    assert state.collapse_all() is False

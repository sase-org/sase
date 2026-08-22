"""Tests for wait-state render-key extraction."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.agent_completion import (
    WaitAgentStatusCounts,
    WaitBeadStatusCounts,
    WaitDependencyStatusCounts,
)
from sase.ace.tui.widgets._agent_list_rendering import agent_render_key

from ._agent_render_cache_helpers import agent as _agent


def test_render_key_changes_each_second_for_waiting_time_floor() -> None:
    a = _agent(status="WAITING")
    a.wait_until = "2026-04-25T14:35:00"

    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 0),
        wait_deps_satisfied=True,
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 1),
        wait_deps_satisfied=True,
    )

    assert k1 != k2


def test_render_key_changes_when_wait_deps_satisfied_flips() -> None:
    a = _agent(status="WAITING")
    a.wait_until = "2026-04-25T14:35:00"
    a.waiting_for = ["dep"]
    now = datetime(2026, 4, 25, 14, 30, 0)

    pending_key = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=now,
        wait_deps_satisfied=False,
    )
    satisfied_key = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=now,
        wait_deps_satisfied=True,
    )

    assert pending_key != satisfied_key


def test_render_key_changes_when_wait_dependency_counts_change() -> None:
    agent = _agent(status="WAITING")
    agent.waiting_for = ["ghost_deploy"]

    known_key = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
        wait_dependency_counts=WaitDependencyStatusCounts(),
    )
    missing_key = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
        wait_dependency_counts=WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(unknown=1)
        ),
    )

    assert known_key != missing_key


def test_render_key_changes_when_agent_or_bead_wait_counts_change() -> None:
    agent = _agent(status="WAITING")
    agent.waiting_for = ["builder"]
    agent.waiting_for_beads = ["run-bead"]
    key_kwargs = {
        "index": 0,
        "is_selected": False,
        "fold_annotation": "",
        "is_expanded": False,
        "is_marked": False,
        "hint_char": None,
        "now": None,
    }
    running_open = agent_render_key(
        agent,
        **key_kwargs,
        wait_dependency_counts=WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(running=1),
            beads=WaitBeadStatusCounts(open=1),
        ),
    )
    running_closed = agent_render_key(
        agent,
        **key_kwargs,
        wait_dependency_counts=WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(running=1),
            beads=WaitBeadStatusCounts(closed=1),
        ),
    )
    done_open = agent_render_key(
        agent,
        **key_kwargs,
        wait_dependency_counts=WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(done=1),
            beads=WaitBeadStatusCounts(open=1),
        ),
    )
    agent_unknown = agent_render_key(
        agent,
        **key_kwargs,
        wait_dependency_counts=WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(unknown=1)
        ),
    )
    bead_unknown = agent_render_key(
        agent,
        **key_kwargs,
        wait_dependency_counts=WaitDependencyStatusCounts(
            beads=WaitBeadStatusCounts(unknown=1)
        ),
    )

    assert running_open != running_closed
    assert running_open != done_open
    assert agent_unknown != bead_unknown
    assert hash(
        WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(running=1),
            beads=WaitBeadStatusCounts(open=1),
        )
    ) == hash(
        WaitDependencyStatusCounts(
            agents=WaitAgentStatusCounts(running=1),
            beads=WaitBeadStatusCounts(open=1),
        )
    )


def test_render_key_changes_when_unresolvable_wait_target_flag_flips() -> None:
    agent = _agent(status="WAITING")
    agent.waiting_for = ["@default"]

    pending_key = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
        has_unresolvable_wait_target=False,
    )
    unresolvable_key = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
        has_unresolvable_wait_target=True,
    )

    assert pending_key != unresolvable_key


def test_render_key_changes_when_runner_slot_count_changes() -> None:
    agent = _agent(status="WAITING")
    agent.wait_runners = 9
    agent.slot_requested_at = "2026-07-12T12:00:00Z"
    agent.runner_slots_in_use = 10

    first = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    agent.runner_slots_in_use = 9
    second = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    assert first != second


def test_render_key_changes_when_wait_priority_changes() -> None:
    agent = _agent(status="WAITING")
    agent.wait_runners = 9
    agent.slot_requested_at = "2026-07-12T12:00:00Z"
    agent.runner_slots_in_use = 10
    agent.wait_priority = 20
    agent.wait_priority_explicit = True

    first = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    agent.wait_priority = 5
    second = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    assert first != second


def test_render_key_changes_when_wait_priority_explicit_flag_changes() -> None:
    agent = _agent(status="WAITING")
    agent.wait_runners = 9
    agent.slot_requested_at = "2026-07-12T12:00:00Z"
    agent.runner_slots_in_use = 10
    agent.wait_priority = 20

    first = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    agent.wait_priority_explicit = True
    second = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    assert first != second


def test_render_key_uses_wait_display_source_timer_fields() -> None:
    root = _agent(status="WAITING")
    child = _agent(
        cl_name="child",
        status="WAITING",
        raw_suffix="20260425143100",
    )
    child.waiting_for = ["dep"]
    child.wait_duration = 300.0
    root.wait_display_source = child
    now = datetime(2026, 4, 25, 14, 30, 0)

    pending_key = agent_render_key(
        root,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=now,
        wait_deps_satisfied=True,
    )
    child.wait_until = "2026-04-25T14:35:00"
    live_key = agent_render_key(
        root,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=now,
        wait_deps_satisfied=True,
    )

    assert pending_key != live_key

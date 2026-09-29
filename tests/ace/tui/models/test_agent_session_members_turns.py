"""Turn-projection tests for sequential agent sessions.

Monitor and gate lanes in the turn projection: ordering against planner
anchors and continuations, identity dedupe, cycle termination, and attach
container reachability.
"""

from __future__ import annotations

from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.models.agent_session_members import (
    concrete_agent_session_member_rows,
    concrete_agent_statuses,
    concrete_agent_session_turn_rows,
    current_agent_session_turn_row,
)
from tests.ace.tui.models._agent_session_members_helpers import (
    make_agent,
    make_gate_member,
    make_monitor_member,
    make_plan_root,
    make_plan_root_with_main_step,
)

__all__ = [
    "test_attach_agent_session_containers_reaches_nested_monitor_without_rerooting",
    "test_gate_agent_session_member_rows_do_not_count_as_agents",
    "test_gate_starter_root_still_counts_as_concrete_agent",
    "test_monitor_agent_session_member_rows_do_not_count_as_agents",
    "test_monitor_starter_root_still_counts_as_concrete_agent",
    "test_nested_monitor_follows_mid_agent_session_continuation",
    "test_planner_step_projection_keeps_every_monitor",
    "test_root_monitor_follows_its_planner_step_anchor",
    "test_root_monitor_follows_root_when_no_step_is_loaded",
    "test_root_monitor_precedes_later_continuations",
    "test_settling_gate_can_be_current_agent_session_turn",
    "test_turn_projection_dedupes_overlapping_links_and_identity",
    "test_turn_projection_terminates_on_cycles",
]


def test_monitor_agent_session_member_rows_do_not_count_as_agents() -> None:
    root = make_agent("alpha--0", role="root")
    monitor = make_agent(
        "alpha--mon",
        role="monitor",
        parent_timestamp=root.raw_suffix,
        status="MONITORING",
        status_bucket="Running",
    )
    monitor.monitor_id = "m123"
    monitor.monitor_state = "running"
    root.followup_agents = [monitor]

    assert concrete_agent_session_turn_rows(root) == (root, monitor)
    assert concrete_agent_session_member_rows(root) == (root,)
    assert [entry.agent for entry in concrete_agent_statuses(root)] == [root]


def test_gate_agent_session_member_rows_do_not_count_as_agents() -> None:
    root = make_agent("alpha--0", role="root")
    gate = make_gate_member(
        "alpha--gate",
        root=root,
        gate_id="g123",
        gate_state="pending",
    )
    root.followup_agents = [gate]

    assert gate.is_gate is True
    assert concrete_agent_session_turn_rows(root) == (root, gate)
    assert concrete_agent_session_member_rows(root) == (root,)
    assert [entry.agent for entry in concrete_agent_statuses(root)] == [root]


def test_gate_starter_root_still_counts_as_concrete_agent() -> None:
    root = make_agent("alpha--0", role="root", status="DONE", status_bucket="Done")
    root.gate_id = "g123"
    gate = make_gate_member(
        "alpha--gate",
        root=root,
        gate_id="g123",
        gate_state="answered",
        stop_offset=5,
    )
    root.followup_agents = [gate]

    assert root.is_gate is False
    assert concrete_agent_session_turn_rows(root) == (root, gate)
    assert concrete_agent_session_member_rows(root) == (root,)
    assert [entry.agent for entry in concrete_agent_statuses(root)] == [root]


def test_settling_gate_can_be_current_agent_session_turn() -> None:
    root = make_agent("alpha--0", role="root")
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="DONE",
        status_bucket="Done",
        stop_offset=2,
    )
    gate = make_gate_member(
        "alpha--gate",
        root=root,
        gate_id="g123",
        gate_state="settling",
        stop_offset=None,
    )
    root.followup_agents = [coder, gate]

    assert current_agent_session_turn_row(root) is gate


def test_monitor_starter_root_still_counts_as_concrete_agent() -> None:
    root = make_agent("alpha--0", role="root", status="DONE", status_bucket="Done")
    root.role_suffix = "--0"
    root.monitor_id = "m123"
    monitor = make_agent(
        "alpha--mon",
        role="monitor",
        parent_timestamp=root.raw_suffix,
        status="MONITORED",
        status_bucket="Done",
    )
    monitor.monitor_id = "m123"
    monitor.monitor_state = "completed"
    root.followup_agents = [monitor]

    assert root.is_monitor is False
    assert concrete_agent_session_turn_rows(root) == (root, monitor)
    assert concrete_agent_session_member_rows(root) == (root,)
    assert [entry.agent for entry in concrete_agent_statuses(root)] == [root]


def test_root_monitor_follows_its_planner_step_anchor() -> None:
    root, main_step = make_plan_root_with_main_step()
    monitor = make_monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m-root",
        monitor_state="running",
    )
    root.runtime_children = [main_step, monitor]
    root.followup_agents = [monitor]

    assert concrete_agent_session_turn_rows(root) == (main_step, monitor)


def test_root_monitor_precedes_later_continuations() -> None:
    root, main_step = make_plan_root_with_main_step()
    root_monitor = make_monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m-root",
        monitor_state="completed",
        stop_offset=5,
    )
    continuation = make_agent(
        "alpha--1",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=2,
    )
    continuation_monitor = make_monitor_member(
        "alpha--mon-0",
        root=continuation,
        monitor_id="m-cont",
        monitor_state="running",
    )
    root.runtime_children = [main_step, continuation, root_monitor]
    root.followup_agents = [continuation, root_monitor]
    continuation.runtime_children = [continuation_monitor]
    continuation.followup_agents = [continuation_monitor]

    assert concrete_agent_session_turn_rows(root) == (
        main_step,
        root_monitor,
        continuation,
        continuation_monitor,
    )


def test_planner_step_projection_keeps_every_monitor() -> None:
    root, main_step = make_plan_root_with_main_step()
    root_monitor = make_monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m-root",
        monitor_state="completed",
        stop_offset=5,
    )
    continuation = make_agent(
        "alpha--1",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=2,
    )
    continuation_monitor = make_monitor_member(
        "alpha--mon-0",
        root=continuation,
        monitor_id="m-cont",
        monitor_state="running",
    )
    root.runtime_children = [main_step, continuation, root_monitor]
    root.followup_agents = [continuation, root_monitor]
    continuation.runtime_children = [continuation_monitor]
    continuation.followup_agents = [continuation_monitor]

    loaded = {
        main_step.identity,
        root_monitor.identity,
        continuation.identity,
        continuation_monitor.identity,
    }
    assert {row.identity for row in concrete_agent_session_turn_rows(root)} == loaded


def test_root_monitor_follows_root_when_no_step_is_loaded() -> None:
    root = make_plan_root()
    monitor = make_monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m-root",
        monitor_state="running",
    )
    root.followup_agents = [monitor]

    assert concrete_agent_session_turn_rows(root) == (root, monitor)


def test_nested_monitor_follows_mid_agent_session_continuation() -> None:
    root = make_agent("alpha--0", role="root")
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    monitor = make_monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-nested",
        monitor_state="running",
    )
    review = make_agent(
        "alpha--review",
        role="review",
        parent_timestamp=root.raw_suffix,
        start_offset=2,
    )
    root.runtime_children = [coder, review]
    root.followup_agents = [coder, review]
    coder.runtime_children = [monitor]
    coder.followup_agents = [monitor]

    assert concrete_agent_session_turn_rows(root) == (root, coder, monitor, review)
    assert concrete_agent_session_member_rows(root) == (root, coder, review)
    assert [entry.agent for entry in concrete_agent_statuses(root)] == [
        root,
        coder,
        review,
    ]


def test_turn_projection_dedupes_overlapping_links_and_identity() -> None:
    root = make_agent("alpha--0", role="root")
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    monitor = make_monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-overlap",
        monitor_state="running",
    )
    alias = make_monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-overlap",
        monitor_state="running",
    )
    alias.raw_suffix = monitor.raw_suffix
    root.runtime_children = [coder]
    root.followup_agents = [coder]
    coder.runtime_children = [monitor]
    coder.followup_agents = [alias]

    assert concrete_agent_session_turn_rows(root) == (root, coder, monitor)
    assert concrete_agent_session_member_rows(root) == (root, coder)


def test_turn_projection_terminates_on_cycles() -> None:
    root = make_agent("alpha--0", role="root")
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    monitor = make_monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-cycle",
        monitor_state="running",
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]
    coder.runtime_children = [monitor]
    monitor.runtime_children = [root]

    assert concrete_agent_session_turn_rows(root) == (root, coder, monitor)


def test_attach_agent_session_containers_reaches_nested_monitor_without_rerooting() -> (
    None
):
    root = make_agent("alpha--0", role="root")
    root.plan_chain_root = True
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        start_offset=1,
    )
    monitor = make_monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-attach",
        monitor_state="completed",
        stop_offset=5,
    )

    _apply_status_overrides([root, coder, monitor])
    ordered = sort_and_reorder([root, coder, monitor], [])

    assert root in ordered
    assert coder.agent_session_container is root
    assert monitor.agent_session_container is root
    assert monitor in coder.runtime_children
    assert monitor not in root.runtime_children

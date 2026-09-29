"""Current-turn and lane-entry tests for sequential agent sessions.

Which row counts as the active turn, and how failed-monitor follow-ups
map to lane status entries.
"""

from __future__ import annotations

from sase.ace.tui.models.agent_session_members import current_agent_session_turn_row
from tests.ace.tui.models._agent_session_members_helpers import (
    make_agent,
    make_monitor_member,
)

__all__ = [
    "test_current_agent_session_turn_ignores_waiting_and_parallel_agent_sessions",
    "test_current_agent_session_turn_returns_none_without_active_turn",
    "test_current_agent_session_turn_selects_active_promoted_root",
    "test_current_agent_session_turn_selects_later_serial_continuation",
    "test_current_agent_session_turn_selects_nested_running_monitor",
    "test_current_agent_session_turn_uses_newest_active_candidate_in_chain_order",
    "test_lane_entries_keep_failed_bucket_when_followup_errored",
    "test_lane_entries_map_final_launched_monitor_to_running",
    "test_lane_entries_skip_non_final_failed_monitor_with_launched_followup",
]


def test_current_agent_session_turn_selects_active_promoted_root() -> None:
    root = make_agent("alpha--0", role="root", status="RUNNING")
    waiting_child = make_agent(
        "alpha--review",
        role="review",
        parent_timestamp=root.raw_suffix,
        status="WAITING",
        start_offset=1,
    )
    root.followup_agents = [waiting_child]

    assert current_agent_session_turn_row(root) is root


def test_current_agent_session_turn_selects_later_serial_continuation() -> None:
    root = make_agent("alpha--0", role="root", status="DONE", stop_offset=1)
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="RUNNING",
        start_offset=2,
    )
    queued = make_agent(
        "alpha--review",
        role="review",
        parent_timestamp=root.raw_suffix,
        status="QUEUED",
        start_offset=3,
    )
    root.runtime_children = [coder, queued]
    root.followup_agents = [coder, queued]

    assert current_agent_session_turn_row(root) is coder


def test_current_agent_session_turn_selects_nested_running_monitor() -> None:
    root = make_agent("alpha--0", role="root", status="DONE", stop_offset=1)
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="DONE",
        start_offset=2,
        stop_offset=3,
    )
    monitor = make_monitor_member(
        "alpha--mon",
        root=coder,
        monitor_id="m-running",
        monitor_state="running",
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]
    coder.runtime_children = [monitor]
    coder.followup_agents = [monitor]

    assert current_agent_session_turn_row(root) is monitor


def test_current_agent_session_turn_returns_none_without_active_turn() -> None:
    root = make_agent("alpha--0", role="root", status="DONE", stop_offset=1)
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="DONE",
        start_offset=2,
        stop_offset=3,
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]

    assert current_agent_session_turn_row(root) is None


def test_current_agent_session_turn_ignores_waiting_and_parallel_agent_sessions() -> (
    None
):
    root = make_agent("alpha--0", role="root", status="DONE", stop_offset=1)
    waiting = make_agent(
        "alpha--review",
        role="review",
        parent_timestamp=root.raw_suffix,
        status="WAITING",
        start_offset=2,
    )
    root.runtime_children = [waiting]
    root.followup_agents = [waiting]

    parallel = make_agent("parallel", role="root", status="RUNNING")
    parallel.agent_session_parallel = True
    parallel_child = make_agent(
        "parallel--1",
        role="phase",
        parent_timestamp=parallel.raw_suffix,
        status="RUNNING",
    )
    parallel_child.agent_session_parallel = True
    parallel.runtime_children = [parallel_child]
    parallel.followup_agents = [parallel_child]

    assert current_agent_session_turn_row(root) is None
    assert current_agent_session_turn_row(parallel) is None


def test_current_agent_session_turn_uses_newest_active_candidate_in_chain_order() -> (
    None
):
    root = make_agent("alpha--0", role="root", status="RUNNING")
    coder = make_agent(
        "alpha--code",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="RUNNING",
        start_offset=1,
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]

    assert current_agent_session_turn_row(root) is coder


def _failed_monitor(
    name: str,
    *,
    root,
    status_bucket: str = "Failed",
    followup_outcome: str | None = None,
    followup_error: str | None = None,
    next_action: str | None = None,
) -> object:
    monitor = make_agent(
        name,
        role="monitor",
        parent_timestamp=root.raw_suffix,
        status="TESTED",
        status_bucket=status_bucket,
        start_offset=1,
        stop_offset=2,
    )
    monitor.monitor_id = "m-lane"
    monitor.monitor_state = "failed"
    monitor.monitor_followup_outcome = followup_outcome
    monitor.monitor_followup_error = followup_error
    monitor.monitor_next_action = next_action
    return monitor


def test_lane_entries_skip_non_final_failed_monitor_with_launched_followup() -> None:
    """A handed-off monitor never contributes a Failed lane entry."""
    from sase.ace.tui.models.agent_session_members import (
        agent_session_lane_status_entries,
    )

    root = make_agent("alpha--0", role="root", status="DONE", status_bucket="Done")
    monitor = _failed_monitor("alpha--mon", root=root, followup_outcome="launched")
    continuation = make_agent(
        "alpha--1",
        role="code",
        parent_timestamp=root.raw_suffix,
        status="DONE",
        status_bucket="Done",
        start_offset=3,
    )

    entries = agent_session_lane_status_entries((root, monitor, continuation))

    assert entries
    assert all(bucket != "Failed" for _status, bucket in entries)


def test_lane_entries_map_final_launched_monitor_to_running() -> None:
    """A final failed monitor with a launched follow-up yields Running."""
    from sase.ace.tui.models.agent_session_members import (
        agent_session_lane_status_entries,
    )

    root = make_agent("alpha--0", role="root", status="DONE", status_bucket="Done")
    monitor = _failed_monitor("alpha--mon", root=root, followup_outcome="launched")

    entries = agent_session_lane_status_entries((root, monitor))

    assert entries[-1] == ("TESTED", "Running")


def test_lane_entries_keep_failed_bucket_when_followup_errored() -> None:
    """A follow-up that failed to launch preserves the Failed entry."""
    from sase.ace.tui.models.agent_session_members import (
        agent_session_lane_status_entries,
    )

    root = make_agent("alpha--0", role="root", status="DONE", status_bucket="Done")
    monitor = _failed_monitor(
        "alpha--mon",
        root=root,
        followup_outcome="launched",
        followup_error="boom",
    )

    entries = agent_session_lane_status_entries((root, monitor))

    assert entries[-1] == ("TESTED", "Failed")

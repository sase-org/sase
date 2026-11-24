"""Current-turn and lane-entry tests for sequential agent sessions.

Which row counts as the active turn, and how failed-monitor follow-ups
map to lane status entries.
"""

from __future__ import annotations

from sase.agent.status_buckets import agent_status_bucket
from sase.ace.tui.models._agent_status_apply import apply_status_overrides
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_session_members import (
    agent_session_lone_running_monitor_row,
    agent_session_running_monitor_row,
    current_agent_session_turn_row,
)
from sase.monitor_state import MONITOR_HELD_STATE
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
    "test_plain_agent_session_root_mirrors_newest_failed_member",
    "test_root_rollup_keeps_failed_bucket_when_followup_errored",
    "test_root_rollup_maps_final_launched_monitor_to_running_lane",
    "test_root_rollup_skips_failed_monitor_handed_to_later_continuation",
    "test_running_monitor_row_returns_nested_running_monitor",
    "test_running_monitor_row_returns_none_for_agent_turn",
    "test_running_monitor_row_returns_none_for_settled_monitor",
    "test_running_monitor_row_returns_none_for_non_session_row",
    "test_running_monitor_row_returns_none_for_clan_container",
    "test_lone_running_monitor_row_returns_monitor_when_first_turn_is_done",
    "test_lone_running_monitor_row_returns_none_for_running_agent_turn",
    "test_lone_running_monitor_row_returns_none_for_settled_monitor",
    "test_lone_running_monitor_row_returns_none_for_held_monitor",
    "test_lone_running_monitor_row_returns_none_when_agent_turn_still_in_flight",
    "test_lone_running_monitor_row_returns_none_for_non_session_row",
    "test_lone_running_monitor_row_returns_none_for_clan_container",
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


def test_plain_agent_session_root_mirrors_newest_failed_member() -> None:
    root = make_agent("alpha--0", role="root", status="DONE", status_bucket="Done")
    failed = make_agent(
        "alpha--1",
        role="first",
        parent_timestamp=root.raw_suffix,
        status="FAILED",
        status_bucket="Failed",
        start_offset=1,
        stop_offset=2,
    )
    root.runtime_children = [failed]

    apply_status_overrides([root, failed])

    assert root.status == "FAILED"
    assert agent_status_bucket(root) == "Failed"


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


def test_root_rollup_skips_failed_monitor_handed_to_later_continuation() -> None:
    """A later successful continuation supersedes a failed monitor."""
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
    root.runtime_children = [monitor, continuation]

    apply_status_overrides([root, monitor, continuation])

    assert agent_status_bucket(root) == "Done"


def test_root_rollup_maps_final_launched_monitor_to_running_lane() -> None:
    """A final failed monitor with a launched follow-up yields Running."""
    root = make_agent("alpha--0", role="root", status="DONE", status_bucket="Done")
    monitor = _failed_monitor("alpha--mon", root=root, followup_outcome="launched")
    root.runtime_children = [monitor]

    apply_status_overrides([root, monitor])

    assert root.status == "TESTED"
    assert agent_status_bucket(root) == "Running"


def test_running_monitor_row_returns_nested_running_monitor() -> None:
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

    assert agent_session_running_monitor_row(root) is monitor


def test_running_monitor_row_returns_none_for_agent_turn() -> None:
    root = make_agent("alpha--0", role="root", status="RUNNING")
    waiting_child = make_agent(
        "alpha--review",
        role="review",
        parent_timestamp=root.raw_suffix,
        status="WAITING",
        start_offset=1,
    )
    root.followup_agents = [waiting_child]

    assert agent_session_running_monitor_row(root) is None


def test_running_monitor_row_returns_none_for_settled_monitor() -> None:
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
        monitor_id="m-settled",
        monitor_state="completed",
        stop_offset=4,
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]
    coder.runtime_children = [monitor]
    coder.followup_agents = [monitor]

    assert agent_session_running_monitor_row(root) is None


def test_running_monitor_row_returns_none_for_non_session_row() -> None:
    agent = make_agent("solo", role="code", status="RUNNING")
    agent.agent_session = None

    assert agent_session_running_monitor_row(agent) is None


def test_running_monitor_row_returns_none_for_clan_container() -> None:
    member = make_agent("bench.1", role="code", status="DONE", stop_offset=1)
    member.agent_clan = "bench"
    member.agent_clan_generation = "gen-1"
    clan = project_clan_tree([member])[0]

    assert clan.is_clan_container is True
    assert agent_session_running_monitor_row(clan) is None


def _session_with_monitor(
    *,
    root_status: str = "DONE",
    root_stop_offset: int | None = 1,
    monitor_state: str = "running",
    monitor_stop_offset: int | None = None,
    extra_in_flight: bool = False,
) -> tuple[object, object]:
    root = make_agent(
        "alpha--0",
        role="root",
        status=root_status,
        stop_offset=root_stop_offset,
    )
    monitor = make_monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m-lone",
        monitor_state=monitor_state,
        stop_offset=monitor_stop_offset,
    )
    children = [monitor]
    if extra_in_flight:
        coder = make_agent(
            "alpha--code",
            role="code",
            parent_timestamp=root.raw_suffix,
            status="RUNNING",
            start_offset=2,
        )
        children = [coder, monitor]
        coder.runtime_children = [monitor]
        coder.followup_agents = [monitor]
    root.runtime_children = children
    root.followup_agents = children
    return root, monitor


def test_lone_running_monitor_row_returns_monitor_when_first_turn_is_done() -> None:
    root, monitor = _session_with_monitor()

    assert agent_session_lone_running_monitor_row(root) is monitor


def test_lone_running_monitor_row_returns_none_for_running_agent_turn() -> None:
    root = make_agent("alpha--0", role="root", status="RUNNING")
    waiting_child = make_agent(
        "alpha--review",
        role="review",
        parent_timestamp=root.raw_suffix,
        status="WAITING",
        start_offset=1,
    )
    root.followup_agents = [waiting_child]

    assert agent_session_lone_running_monitor_row(root) is None


def test_lone_running_monitor_row_returns_none_for_settled_monitor() -> None:
    root, _monitor = _session_with_monitor(
        monitor_state="completed",
        monitor_stop_offset=2,
    )

    assert agent_session_lone_running_monitor_row(root) is None


def test_lone_running_monitor_row_returns_none_for_held_monitor() -> None:
    root, _monitor = _session_with_monitor(monitor_state=MONITOR_HELD_STATE)

    assert agent_session_lone_running_monitor_row(root) is None


def test_lone_running_monitor_row_returns_none_when_agent_turn_still_in_flight() -> (
    None
):
    root, _monitor = _session_with_monitor(
        root_status="RUNNING",
        root_stop_offset=None,
        extra_in_flight=True,
    )

    assert agent_session_lone_running_monitor_row(root) is None


def test_lone_running_monitor_row_returns_none_for_non_session_row() -> None:
    agent = make_agent("solo", role="code", status="RUNNING")
    agent.agent_session = None

    assert agent_session_lone_running_monitor_row(agent) is None


def test_lone_running_monitor_row_returns_none_for_clan_container() -> None:
    member = make_agent("bench.1", role="code", status="DONE", stop_offset=1)
    member.agent_clan = "bench"
    member.agent_clan_generation = "gen-1"
    clan = project_clan_tree([member])[0]

    assert clan.is_clan_container is True
    assert agent_session_lone_running_monitor_row(clan) is None


def test_root_rollup_keeps_failed_bucket_when_followup_errored() -> None:
    """A follow-up that failed to launch preserves the Failed entry."""
    root = make_agent("alpha--0", role="root", status="DONE", status_bucket="Done")
    monitor = _failed_monitor(
        "alpha--mon",
        root=root,
        followup_outcome="launched",
        followup_error="boom",
    )
    root.runtime_children = [monitor]

    apply_status_overrides([root, monitor])

    assert root.status == "TESTED"
    assert agent_status_bucket(root) == "Failed"

"""Per-family monitor lane-count tests."""

from __future__ import annotations

from sase.ace.tui.models.agent_family_members import (
    MonitorLaneCounts,
    monitor_lane_counts,
    monitor_row_is_settled,
)

from ._agent_family_members_helpers import _agent, _monitor_member


def test_monitor_row_is_settled_matches_lane_partition() -> None:
    running = _monitor_member(
        "alpha--mon-running",
        root=_agent("alpha--0", role="root"),
        monitor_id="m-running",
        monitor_state="running",
    )
    assert monitor_row_is_settled(running) is False

    for state in ("completed", "stopped", "failed", "timeout", "lost"):
        settled = _monitor_member(
            f"alpha--mon-{state}",
            root=_agent("alpha--0", role="root"),
            monitor_id=state,
            monitor_state=state,
            stop_offset=5,
        )
        assert monitor_row_is_settled(settled) is True

    unknown = _monitor_member(
        "alpha--mon-unknown",
        root=_agent("alpha--0", role="root"),
        monitor_id="m-unknown",
        monitor_state=None,
    )
    assert monitor_row_is_settled(unknown) is False

    unknown_stopped = _monitor_member(
        "alpha--mon-unknown-stopped",
        root=_agent("alpha--0", role="root"),
        monitor_id="m-unknown-stopped",
        monitor_state=None,
        stop_offset=5,
    )
    assert monitor_row_is_settled(unknown_stopped) is True


def test_monitor_lane_counts_partitions_running_and_every_terminal_state() -> None:
    root = _agent("alpha--0", role="root")
    running = _monitor_member(
        "alpha--mon-running", root=root, monitor_id="m1", monitor_state="running"
    )
    monitors = [running] + [
        _monitor_member(
            f"alpha--mon-{state}",
            root=root,
            monitor_id=state,
            monitor_state=state,
            stop_offset=5,
        )
        for state in ("completed", "stopped", "failed", "timeout", "lost")
    ]
    root.followup_agents = monitors

    lanes = monitor_lane_counts(root)

    assert lanes == MonitorLaneCounts(running=1, settled=5)
    assert lanes.running + lanes.settled == len(monitors)


def test_monitor_lane_counts_unknown_state_without_stop_time_counts_running() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon", root=root, monitor_id="m1", monitor_state=None
    )
    root.followup_agents = [monitor]

    assert monitor_lane_counts(root) == MonitorLaneCounts(running=1, settled=0)


def test_monitor_lane_counts_unknown_state_with_stop_time_counts_settled() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m1",
        monitor_state=None,
        stop_offset=5,
    )
    root.followup_agents = [monitor]

    assert monitor_lane_counts(root) == MonitorLaneCounts(running=0, settled=1)


def test_monitor_lane_counts_running_state_with_stop_time_counts_settled() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m1",
        monitor_state="running",
        stop_offset=5,
    )
    root.followup_agents = [monitor]

    assert monitor_lane_counts(root) == MonitorLaneCounts(running=0, settled=1)


def test_monitor_lane_counts_aggregates_clan_members_at_depth_two() -> None:
    clan = _agent("workers", role="root")
    clan.is_clan_container = True

    family_a = _agent("alpha--0", role="root")
    monitor_a = _monitor_member(
        "alpha--mon", root=family_a, monitor_id="ma", monitor_state="running"
    )
    family_a.followup_agents = [monitor_a]

    family_b = _agent("beta--0", role="root")
    monitor_b = _monitor_member(
        "beta--mon",
        root=family_b,
        monitor_id="mb",
        monitor_state="completed",
        stop_offset=5,
    )
    family_b.followup_agents = [monitor_b]

    clan.runtime_children = [family_a, family_b]

    assert monitor_lane_counts(clan) == MonitorLaneCounts(running=1, settled=1)


def test_monitor_lane_counts_dedupes_overlap_and_terminates_on_cycles() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon", root=root, monitor_id="m1", monitor_state="running"
    )
    # Real family rows attach the same member to both lists.
    root.runtime_children = [monitor]
    root.followup_agents = [monitor]
    # A cycle back to the root: without a cycle guard this would recurse
    # forever.
    monitor.runtime_children = [root]

    assert monitor_lane_counts(root) == MonitorLaneCounts(running=1, settled=0)


def test_monitor_lane_counts_returns_zero_for_plain_agent() -> None:
    agent = _agent("alpha--code", role="code")

    assert monitor_lane_counts(agent) == MonitorLaneCounts()

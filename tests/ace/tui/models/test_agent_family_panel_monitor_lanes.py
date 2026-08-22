"""Panel-wide monitor lane-count tests."""

from __future__ import annotations

from sase.ace.tui.models.agent_family_members import (
    MonitorLaneCounts,
    panel_monitor_lane_counts,
)

from ._agent_family_members_helpers import _agent, _monitor_member


def test_panel_monitor_lane_counts_partitions_across_top_level_rows() -> None:
    root_a = _agent("alpha--0", role="root")
    root_a.followup_agents = [
        _monitor_member(
            "alpha--mon-running", root=root_a, monitor_id="ma", monitor_state="running"
        )
    ]
    root_b = _agent("beta--0", role="root")
    root_b.followup_agents = [
        _monitor_member(
            "beta--mon-done",
            root=root_b,
            monitor_id="mb",
            monitor_state="completed",
            stop_offset=5,
        )
    ]

    assert panel_monitor_lane_counts([root_a, root_b]) == MonitorLaneCounts(
        running=1, settled=1
    )


def test_panel_monitor_lane_counts_dedupes_monitor_reachable_from_two_roots() -> None:
    shared_root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon", root=shared_root, monitor_id="m1", monitor_state="running"
    )
    root_a = _agent("alpha--0", role="root")
    root_a.runtime_children = [monitor]
    root_b = _agent("alpha--1", role="root")
    root_b.followup_agents = [monitor]

    assert panel_monitor_lane_counts([root_a, root_b]) == MonitorLaneCounts(
        running=1, settled=0
    )


def test_panel_monitor_lane_counts_counts_a_top_level_monitor_row() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon",
        root=root,
        monitor_id="m1",
        monitor_state="completed",
        stop_offset=5,
    )

    assert panel_monitor_lane_counts([monitor]) == MonitorLaneCounts(
        running=0, settled=1
    )


def test_panel_monitor_lane_counts_reaches_monitor_nested_two_levels_down() -> None:
    clan = _agent("workers", role="root")
    clan.is_clan_container = True
    family = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon",
        root=family,
        monitor_id="m1",
        monitor_state="completed",
        stop_offset=5,
    )
    family.followup_agents = [monitor]
    clan.runtime_children = [family]

    assert panel_monitor_lane_counts([clan]) == MonitorLaneCounts(running=0, settled=1)


def test_panel_monitor_lane_counts_stop_time_without_state_counts_settled() -> None:
    root = _agent("alpha--0", role="root")
    settled = _monitor_member(
        "alpha--mon-settled",
        root=root,
        monitor_id="m1",
        monitor_state=None,
        stop_offset=5,
    )
    running = _monitor_member(
        "alpha--mon-running", root=root, monitor_id="m2", monitor_state=None
    )
    root.followup_agents = [settled, running]

    assert panel_monitor_lane_counts([root]) == MonitorLaneCounts(running=1, settled=1)


def test_panel_monitor_lane_counts_empty_and_monitor_free_input() -> None:
    assert panel_monitor_lane_counts([]) == MonitorLaneCounts()

    plain = _agent("alpha--code", role="code")
    assert panel_monitor_lane_counts([plain]) == MonitorLaneCounts()


def test_panel_monitor_lane_counts_terminates_on_a_cycle() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon", root=root, monitor_id="m1", monitor_state="running"
    )
    root.runtime_children = [monitor]
    monitor.runtime_children = [root]

    assert panel_monitor_lane_counts([root]) == MonitorLaneCounts(running=1, settled=0)

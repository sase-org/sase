"""Panel-wide gate lane-count tests."""

from __future__ import annotations

from sase.ace.tui.models.agent_family_members import (
    ShellLaneCounts,
    _GateLaneCounts,
    _MonitorLaneCounts,
    panel_shell_lane_counts,
)

from ._agent_family_members_helpers import _agent, _gate_member, _monitor_member


def _panel_monitor_lane_counts(rows):
    return panel_shell_lane_counts(rows).monitor


def test_panel_shell_lane_counts_partitions_gates_across_top_level_rows() -> None:
    root_a = _agent("alpha--0", role="root")
    root_a.followup_agents = [
        _gate_member(
            "alpha--gate-running", root=root_a, gate_id="ga", gate_state="pending"
        )
    ]
    root_b = _agent("beta--0", role="root")
    root_b.followup_agents = [
        _gate_member(
            "beta--gate-done",
            root=root_b,
            gate_id="gb",
            gate_state="answered",
            stop_offset=5,
        )
    ]
    root_c = _agent("gamma--0", role="root")
    root_c.followup_agents = [
        _gate_member(
            "gamma--gate-failed",
            root=root_c,
            gate_id="gc",
            gate_state="timeout",
            stop_offset=5,
        )
    ]

    assert panel_shell_lane_counts([root_a, root_b, root_c]).gate == _GateLaneCounts(
        running=1,
        settled=1,
        failed=1,
    )


def test_panel_shell_lane_counts_keeps_monitor_compatibility_helper() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon", root=root, monitor_id="m1", monitor_state="running"
    )
    gate = _gate_member("alpha--gate", root=root, gate_id="g1", gate_state="pending")
    root.followup_agents = [monitor, gate]

    assert panel_shell_lane_counts([root]) == ShellLaneCounts(
        monitor=_MonitorLaneCounts(running=1, settled=0),
        gate=_GateLaneCounts(running=1, settled=0, failed=0),
    )
    assert _panel_monitor_lane_counts([root]) == _MonitorLaneCounts(
        running=1, settled=0
    )

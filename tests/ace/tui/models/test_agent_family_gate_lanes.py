"""Per-family gate lane-count tests."""

from __future__ import annotations

from sase.ace.tui.models.agent_family_members import (
    ShellLaneCounts,
    _GateLaneCounts,
    _MonitorLaneCounts,
    gate_row_is_settled,
    shell_lane_counts,
)

from ._agent_family_members_helpers import _agent, _gate_member, _monitor_member


def _gate_lane_counts(agent):
    return shell_lane_counts(agent).gate


def test_gate_row_is_settled_matches_lane_partition() -> None:
    root = _agent("alpha--0", role="root")
    pending = _gate_member(
        "alpha--gate-pending", root=root, gate_id="g-pending", gate_state="pending"
    )
    assert gate_row_is_settled(pending) is False

    settling = _gate_member(
        "alpha--gate-settling", root=root, gate_id="g-settling", gate_state="settling"
    )
    assert gate_row_is_settled(settling) is False

    for state in ("answered", "completed", "stopped", "failed", "timeout", "lost"):
        settled = _gate_member(
            f"alpha--gate-{state}",
            root=root,
            gate_id=state,
            gate_state=state,
            stop_offset=5,
        )
        assert gate_row_is_settled(settled) is True


def test_gate_lane_counts_partitions_alive_settled_and_failed_states() -> None:
    root = _agent("alpha--0", role="root")
    gates = [
        _gate_member(
            "alpha--gate-pending",
            root=root,
            gate_id="pending",
            gate_state="pending",
        ),
        _gate_member(
            "alpha--gate-settling",
            root=root,
            gate_id="settling",
            gate_state="settling",
        ),
        *[
            _gate_member(
                f"alpha--gate-{state}",
                root=root,
                gate_id=state,
                gate_state=state,
                stop_offset=5,
            )
            for state in ("answered", "completed", "stopped")
        ],
        *[
            _gate_member(
                f"alpha--gate-{state}",
                root=root,
                gate_id=state,
                gate_state=state,
                stop_offset=5,
            )
            for state in ("failed", "timeout", "lost")
        ],
    ]
    root.followup_agents = gates

    assert _gate_lane_counts(root) == _GateLaneCounts(
        running=2,
        settled=3,
        failed=3,
    )


def test_gate_lane_counts_stop_time_without_state_counts_settled() -> None:
    root = _agent("alpha--0", role="root")
    gate = _gate_member(
        "alpha--gate",
        root=root,
        gate_id="g1",
        gate_state=None,
        stop_offset=5,
    )
    root.followup_agents = [gate]

    assert _gate_lane_counts(root) == _GateLaneCounts(running=0, settled=1, failed=0)


def test_shell_lane_counts_preserves_monitor_and_gate_partitions() -> None:
    root = _agent("alpha--0", role="root")
    monitor = _monitor_member(
        "alpha--mon", root=root, monitor_id="m1", monitor_state="running"
    )
    gate = _gate_member(
        "alpha--gate",
        root=root,
        gate_id="g1",
        gate_state="failed",
        stop_offset=5,
    )
    root.runtime_children = [monitor, gate]
    root.followup_agents = [monitor, gate]

    counts = shell_lane_counts(root)

    assert counts == ShellLaneCounts(
        monitor=_MonitorLaneCounts(running=1, settled=0),
        gate=_GateLaneCounts(running=0, settled=0, failed=1),
    )

"""Decision parity between full and capacity-only artifact scans."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from sase.core.runner_slots import (
    runner_capacity_snapshot,
    runner_slot_candidate_record,
)


def _write_marker(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _artifact(
    root: Path,
    timestamp: str,
    meta: dict[str, Any],
    *,
    waiting: dict[str, Any] | None = None,
    done: bool = False,
) -> Path:
    artifact_dir = root / "proj" / "artifacts" / "ace-run" / timestamp
    _write_marker(artifact_dir / "agent_meta.json", meta)
    if waiting is not None:
        _write_marker(artifact_dir / "waiting.json", waiting)
    if done:
        _write_marker(artifact_dir / "done.json", {"done": True})
    return artifact_dir


def test_capacity_only_scan_preserves_admission_and_candidate_decisions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "projects"
    project = root / "proj"
    project.mkdir(parents=True)
    (project / "proj.sase").write_text("PROJECT_STATE: active\n", encoding="utf-8")

    live_pid = os.getpid()
    _artifact(
        root,
        "20261026090000",
        {
            "name": "live",
            "pid": live_pid,
            "run_started_at": "2026-10-26T09:00:00Z",
            "queue_weight": 1.0,
            "agent_clan": "research",
            "agent_clan_generation": "generation-1",
        },
    )
    _artifact(
        root,
        "20261026080000",
        {"name": "stopped-parent", "pid": 2**30, "stopped_at": "2026-10-26T08:01:00Z"},
    )
    _artifact(
        root,
        "20261026080001",
        {
            "name": "lineage-child",
            "pid": live_pid,
            "parent_timestamp": "20261026080000",
            "run_started_at": "2026-10-26T08:00:01Z",
            "queue_weight": 1.0,
        },
    )
    _artifact(
        root,
        "20261026070000",
        {
            "name": "clan-tribe-member",
            "pid": 2**30,
            "stopped_at": "2026-10-26T07:01:00Z",
            "agent_clan": "research",
            "agent_clan_generation": "generation-1",
            "clan_tribe": "chop",
        },
    )
    _artifact(
        root,
        "20261026060000",
        {"name": "dead-waiter", "pid": 2**30},
        waiting={"slot_requested_at": "2026-10-26T06:00:00Z"},
    )
    _artifact(
        root,
        "20261026050000",
        {"name": "stopped-with-waiting", "stopped_at": "2026-10-26T05:01:00Z"},
        waiting={"slot_requested_at": "2026-10-26T05:00:00Z"},
    )
    _artifact(root, "20261026040000", {"name": "unknown-pid"})
    _artifact(
        root,
        "20261026030000",
        {"name": "done", "pid": 2**30},
        done=True,
    )
    _artifact(
        root,
        "20261026020000",
        {
            "name": "stopped-only",
            "pid": 2**30,
            "stopped_at": "2026-10-26T02:01:00Z",
        },
    )

    full = scan_agent_artifacts(root)
    capacity = scan_agent_artifacts(
        root, AgentArtifactScanOptionsWire(capacity_only=True)
    )
    non_done = [record for record in full.records if not record.has_done_marker]
    capacity_timestamps = {record.timestamp for record in capacity.records}
    assert "20261026080000" in capacity_timestamps  # lineage re-admission
    assert "20261026070000" in capacity_timestamps  # clan-tribe re-admission
    assert "20261026060000" not in capacity_timestamps  # dead-pid waiter
    assert "20261026030000" not in capacity_timestamps  # done
    assert "20261026020000" not in capacity_timestamps  # stopped, no live markers

    def is_live(record) -> bool:
        meta = record.agent_meta
        pid = None if meta is None else meta.pid
        if not isinstance(pid, int) or pid <= 1:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def snapshot(records, candidate):
        return runner_capacity_snapshot(
            records,
            is_live,
            effective_limit=3.0,
            now="2026-10-26T09:30:00Z",
            candidate=candidate,
        )

    def admission_view(result: dict[str, Any]) -> dict[str, Any]:
        # capacity_only may omit never-live dirs from accounting rows; claims,
        # waiters, lineage owners, and occupied weights must still match.
        return {
            "occupied_lanes": result["occupied_lanes"],
            "occupied_capacity": result["occupied_capacity"],
            "claims": result["claims"],
            "waiters": result["waiters"],
            "candidate_decision": result.get("candidate_decision"),
        }

    for index, weight in enumerate((0.5, 1.0, 2.0)):
        candidate = runner_slot_candidate_record(
            artifacts_dir=f"{root}/candidate-{index}",
            timestamp=f"2026102610000{index}",
            slot_requested_at=f"2026-10-26T10:00:0{index}Z",
            wait_priority=10,
            queue_weight=weight,
            queue_weight_explicit=True,
            eligible_since=None,
        )
        assert admission_view(snapshot(capacity.records, candidate)) == admission_view(
            snapshot(non_done, candidate)
        )

    assert admission_view(snapshot(capacity.records, None)) == admission_view(
        snapshot(non_done, None)
    )

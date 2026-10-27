"""Shared harnesses for agent-runner-slot context tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_runner_slots import RunnerCapacitySnapshot
from sase.core.paths import sase_projects_dir


def _agent(name: str, **overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/project/project.sase",
        "status": "WAITING",
        "start_time": datetime(2026, 7, 12, 12, 0),
        "raw_suffix": name,
        "pid": 100,
        "artifacts_dir": f"/tmp/project/artifacts/ace-run/{name}",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _sharded_artifacts_dir(project: str, timestamp: str) -> str:
    """Build a real day-sharded artifact dir under the redirected sase home."""
    return str(
        sase_projects_dir()
        / project
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )


def _assert_capacity_metrics(
    capacity: RunnerCapacitySnapshot,
    expected: tuple[int, int, int],
) -> None:
    assert (
        capacity.effective_limit,
        capacity.slots_in_use,
        capacity.queued_count,
    ) == expected


def _machine_capacity_report_for_waiter(turn: Agent, queue_position: int = 1):
    """Build a minimal authoritative report listing *turn* as queued."""
    import time

    from sase.config.runner_limit_override import EffectiveRunnerLimitSnapshot
    from sase.core.runner_slots import MachineCapacityReport

    now = time.time()
    raw = {
        "occupied_lanes": 0,
        "occupied_capacity": 0.0,
        "effective_limit": 8.0,
        "claims": [],
        "waiters": [
            {
                "artifact_dir": turn.artifacts_dir,
                "queue_position": queue_position,
                "slot_requested_at": turn.slot_requested_at,
            }
        ],
        "accounting": [],
        "accounting_valid": True,
    }
    return MachineCapacityReport(
        machine="athena",
        computed_at=now,
        scanned_at=now,
        token="test-token",
        scan_current=True,
        effective_limit=8.0,
        limit=EffectiveRunnerLimitSnapshot(
            configured_limit=8,
            temporary_override=None,
            captured_at=now,
        ),
        occupied_capacity=0.0,
        occupied_lanes=0,
        over_limit=False,
        claims=(),
        waiters=tuple(raw["waiters"]),
        accounting=(),
        diagnostics=(),
        accounting_valid=True,
        accounting_available=False,
        raw_snapshot=raw,
        record_inputs=(),
    )

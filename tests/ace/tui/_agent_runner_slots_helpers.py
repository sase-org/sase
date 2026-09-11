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

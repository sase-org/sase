"""Tests for related workflow phases that share a runner PID."""

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    WaitingMarkerWire,
)
from sase.core.runner_slots import running_root_agent_count
from tests._agent_loader_helpers import _mock_agent_loader_sources
from tests._workspace_provider_helpers import patch_spy_metadata


@pytest.fixture(autouse=True)
def _register_spy_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_spy_metadata(monkeypatch)


def test_live_family_root_survives_shared_pid_for_runner_slot_context() -> None:
    """A terminal serial phase cannot erase its live root's occupied slot."""
    root_timestamp = "20260721155935"
    child_timestamp = "20260721160507"
    waiter_timestamp = "20260721161000"
    runner_pid = 1729466
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="hc.f0.f0--0",
        project_file="/tmp/project/project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 21, 15, 59, 35),
        run_start_time=datetime(2026, 7, 21, 15, 59, 36),
        workflow="ace(run)",
        raw_suffix=root_timestamp,
        pid=runner_pid,
        runner_is_live=True,
        artifacts_dir=f"/tmp/project/artifacts/ace-run/{root_timestamp}",
        agent_name="hc.f0.f0--0",
        agent_family="hc.f0.f0",
        agent_family_role="root",
    )
    child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="hc.f0.f0--1",
        project_file="/tmp/project/project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 21, 16, 5, 7),
        run_start_time=datetime(2026, 7, 21, 16, 5, 8),
        stop_time=datetime(2026, 7, 21, 16, 8),
        workflow="ace-run",
        raw_suffix=child_timestamp,
        pid=runner_pid,
        artifacts_dir=f"/tmp/project/artifacts/ace-run/{child_timestamp}",
        parent_timestamp=root_timestamp,
        agent_name="hc.f0.f0--1",
        agent_family="hc.f0.f0",
        agent_family_role="code",
        role_suffix=".code",
    )
    waiter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="queued",
        project_file="/tmp/project/project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 21, 16, 10),
        workflow="ace(run)",
        raw_suffix=waiter_timestamp,
        pid=1729999,
        artifacts_dir=f"/tmp/project/artifacts/ace-run/{waiter_timestamp}",
        wait_runners=0,
        wait_runners_explicit=False,
        slot_requested_at="2026-07-21T16:10:00-04:00",
    )

    with _mock_agent_loader_sources(
        running_agents=[root, waiter],
        workflow_agents=[child],
        process_is_running=True,
    ):
        result = load_all_agents()

    assert any(agent is root for agent in result)
    assert any(agent is child for agent in result)
    assert root.runner_is_live is True
    assert child.runner_is_live is False
    assert root.followup_agents == [child]
    assert root.runtime_children == [child]

    capacity = refresh_runner_slot_context(result, effective_limit=1)

    assert (
        capacity.effective_limit,
        capacity.slots_in_use,
        capacity.global_cap_queue_count,
    ) == (1, 1, 1)
    assert waiter.status == "QUEUED"
    assert waiter.runner_slots_in_use == 1
    assert waiter.runner_slot_queue_position == 1
    assert waiter.runner_slot_queue_size == 1

    admission_records = [
        AgentArtifactRecordWire(
            project_name="project",
            project_dir="/tmp/project",
            project_file="/tmp/project/project.sase",
            workflow_dir_name="ace-run",
            artifact_dir=root.artifacts_dir or "",
            timestamp=root_timestamp,
            agent_meta=AgentMetaWire(
                name=root.agent_name,
                pid=runner_pid,
                run_started_at="2026-07-21T15:59:36-04:00",
            ),
        ),
        AgentArtifactRecordWire(
            project_name="project",
            project_dir="/tmp/project",
            project_file="/tmp/project/project.sase",
            workflow_dir_name="ace-run",
            artifact_dir=child.artifacts_dir or "",
            timestamp=child_timestamp,
            agent_meta=AgentMetaWire(
                name=child.agent_name,
                pid=runner_pid,
                parent_timestamp=root_timestamp,
                run_started_at="2026-07-21T16:05:08-04:00",
            ),
            has_done_marker=True,
        ),
        AgentArtifactRecordWire(
            project_name="project",
            project_dir="/tmp/project",
            project_file="/tmp/project/project.sase",
            workflow_dir_name="ace-run",
            artifact_dir=waiter.artifacts_dir or "",
            timestamp=waiter_timestamp,
            agent_meta=AgentMetaWire(name="queued", pid=waiter.pid),
            waiting=WaitingMarkerWire(
                wait_runners=0,
                slot_requested_at=waiter.slot_requested_at,
            ),
        ),
    ]
    admission_count = running_root_agent_count(admission_records, lambda _record: True)
    assert capacity.slots_in_use == admission_count == 1


def test_pid_dedup_preserves_followup_workflow_agents() -> None:
    """Separate plan and code phases survive when their runner PID is shared."""
    plan_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 3, 15, 21, 32, 15),
        workflow="sase",
        raw_suffix="20260315213215",
        pid=1780415,
        role_suffix=".plan",
    )
    code_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 3, 15, 21, 45, 30),
        workflow="sase",
        raw_suffix="20260315214530",
        pid=1780415,
        role_suffix=".code",
    )

    with _mock_agent_loader_sources(
        running_agents=[],
        workflow_agents=[plan_agent, code_agent],
        process_is_running=False,
    ):
        result = load_all_agents()

    assert len(result) == 3
    suffixes = {agent.raw_suffix for agent in result}
    assert "20260315213215" in suffixes
    assert "20260315214530" in suffixes

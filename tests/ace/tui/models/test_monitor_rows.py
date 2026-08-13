"""Monitor row projection tests for TUI loaders."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._loaders._done_loaders import load_done_agents_from_snapshot
from sase.ace.tui.models._loaders._meta_enrichment_wire import (
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
)


def test_running_monitor_meta_projects_start_label_and_bucket() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-row",
        project_file="/tmp/monitor.sase",
        status="STARTING",
        start_time=datetime(2026, 8, 12, 9, 0, 0),
        raw_suffix="20260812090000",
    )

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            name="alpha--mon",
            monitor_id="m123",
            monitor_state="running",
            monitor_command="just check-full",
            monitor_label="just check",
            monitor_start_status="MONITORING",
            monitor_exit_code=None,
            run_started_at="2026-08-12T13:00:00Z",
            agent_family="alpha",
            agent_family_role="monitor",
            role_suffix="--mon",
        ),
        waiting=None,
    )

    assert agent.is_monitor is True
    assert agent.status == "MONITORING"
    assert agent.status_bucket == "Running"
    assert agent.monitor_label == "just check"
    assert agent.monitor_command == "just check-full"


def test_running_monitor_meta_projects_detail_fields() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-row",
        project_file="/tmp/monitor.sase",
        status="STARTING",
        start_time=datetime(2026, 8, 12, 9, 0, 0),
        raw_suffix="20260812090000",
    )

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(
            name="alpha--mon",
            monitor_id="m123",
            monitor_state="running",
            monitor_command="just check-full",
            monitor_label="just check",
            monitor_cwd="/home/bryan/sase",
            monitor_reason="Verify the refactor",
            monitor_next_action="Reply to the user.",
            monitor_timeout_seconds=2700.0,
            monitor_idle_timeout_seconds=600.0,
            monitor_output_truncated=True,
            monitor_start_status="MONITORING",
            monitor_exit_code=None,
            run_started_at="2026-08-12T13:00:00Z",
            agent_family="alpha",
            agent_family_role="monitor",
            role_suffix="--mon",
        ),
        waiting=None,
    )

    assert agent.monitor_cwd == "/home/bryan/sase"
    assert agent.monitor_reason == "Verify the refactor"
    assert agent.monitor_next_action == "Reply to the user."
    assert agent.monitor_timeout_seconds == 2700.0
    assert agent.monitor_idle_timeout_seconds == 600.0
    assert agent.monitor_output_truncated is True


def test_terminal_monitor_done_projects_stop_label_and_exit_code() -> None:
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/.sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[
            AgentArtifactRecordWire(
                project_name="sase",
                project_dir="/tmp/.sase/projects/sase",
                project_file="/tmp/.sase/projects/sase/sase.sase",
                workflow_dir_name="ace-run",
                artifact_dir="/tmp/.sase/projects/sase/artifacts/ace-run/20260812090000",
                timestamp="20260812090000",
                agent_meta=AgentMetaWire(
                    name="alpha--mon",
                    monitor_id="m123",
                    monitor_state="failed",
                    monitor_command="just check-full",
                    monitor_label="just check",
                    monitor_stop_status="CHECKED",
                    monitor_exit_code=1,
                    run_started_at="2026-08-12T13:00:00Z",
                    stopped_at="2026-08-12T13:03:00Z",
                    agent_family="alpha",
                    agent_family_role="monitor",
                    role_suffix="--mon",
                ),
                done=DoneMarkerWire(
                    outcome="monitored",
                    cl_name="monitor-row",
                    project_file="/tmp/.sase/projects/sase/sase.sase",
                    monitor_state="failed",
                    monitor_exit_code=1,
                    status_label="CHECKED",
                ),
                has_done_marker=True,
            )
        ],
    )

    (agent,) = load_done_agents_from_snapshot(snapshot, {}, {})

    assert agent.is_monitor is True
    assert agent.status == "CHECKED"
    assert agent.status_bucket == "Failed"
    assert agent.monitor_state == "failed"
    assert agent.monitor_exit_code == 1

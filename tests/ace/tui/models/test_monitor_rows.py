"""Monitor row projection tests for TUI loaders."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models._loaders._done_loaders import load_done_agents_from_snapshot
from sase.ace.tui.models._loaders._meta_enrichment_wire import (
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models._loaders._workflow_snapshot_loaders import (
    load_workflow_agents_from_snapshot,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from sase.ace.tui.models.artifact_files import get_artifacts_dir
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    WorkflowStateWire,
)
from sase.core.paths import sase_projects_dir


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


def _settled_monitor_record(
    *, done_project_file: str | None = "/tmp/.sase/projects/sase/sase.sase"
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="sase",
        project_dir="/tmp/.sase/projects/sase",
        project_file="/tmp/.sase/projects/sase/sase.sase",
        workflow_dir_name="ace-run",
        artifact_dir="/tmp/.sase/projects/sase/artifacts/ace-run/20260812090000",
        timestamp="20260812090000",
        workflow_state=WorkflowStateWire(
            workflow_name="run",
            status="running",
            pid=999999,
            appears_as_agent=True,
        ),
        done=DoneMarkerWire(
            outcome="monitored",
            cl_name="monitor-row",
            project_file=done_project_file,
            status_label="MONITORED",
        ),
        has_done_marker=True,
    )


def test_settled_monitor_suppresses_workflow_row_but_keeps_done_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A settled monitor's stale workflow_state.json projects no agent row.

    Its ``workflow_state.json`` never leaves ``status: "running"`` and the
    PID it recorded (the starter process) is long dead, so without the
    done-marker skip this would resurface as a phantom FAILED row.
    """
    monkeypatch.setattr(
        "sase.ace.tui.models._loaders._workflow_snapshot_loaders.is_process_running",
        lambda _pid: False,
    )
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/.sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[_settled_monitor_record()],
    )

    workflow_agents = load_workflow_agents_from_snapshot(snapshot)
    (done_agent,) = load_done_agents_from_snapshot(snapshot, {}, {})

    assert workflow_agents == []
    assert done_agent.status == "MONITORED"


def test_settled_monitor_done_row_falls_back_to_record_project_file() -> None:
    """A done marker that omits project_file inherits its record's value.

    This is the shape the real monitor writers emitted before this fix:
    ``build_done_marker()`` always writes ``project_file``, but the three
    hand-rolled monitor marker dicts did not.
    """
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/.sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[_settled_monitor_record(done_project_file=None)],
    )

    (agent,) = load_done_agents_from_snapshot(snapshot, {}, {})

    assert agent.project_file == "/tmp/.sase/projects/sase/sase.sase"


def test_settled_monitor_done_row_keeps_explicit_project_file() -> None:
    """An explicit done-marker project_file still wins over the record's."""
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/.sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[
            _settled_monitor_record(
                done_project_file="/tmp/.sase/projects/other/other.sase"
            )
        ],
    )

    (agent,) = load_done_agents_from_snapshot(snapshot, {}, {})

    assert agent.project_file == "/tmp/.sase/projects/other/other.sase"


def test_running_monitor_workflow_row_still_projects_as_monitoring() -> None:
    """A still-running monitor's workflow row is not over-broadly suppressed."""
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
                artifact_dir=(
                    "/tmp/.sase/projects/sase/artifacts/ace-run/20260812090000"
                ),
                timestamp="20260812090000",
                workflow_state=WorkflowStateWire(
                    workflow_name="run",
                    status="running",
                    pid=None,
                    appears_as_agent=True,
                ),
                agent_meta=AgentMetaWire(
                    name="alpha--mon",
                    monitor_id="m123",
                    monitor_state="running",
                    monitor_command="just check-full",
                    monitor_label="just check",
                    monitor_start_status="MONITORING",
                    monitor_exit_code=None,
                    agent_family="alpha",
                    agent_family_role="monitor",
                    role_suffix="--mon",
                ),
            )
        ],
    )

    (agent,) = load_workflow_agents_from_snapshot(snapshot)

    assert agent.is_monitor is True
    assert agent.status == "MONITORING"


def test_load_all_agents_settled_monitor_projects_one_resolvable_row() -> None:
    """load_all_agents() over a settled monitor snapshot yields one row.

    Regression coverage for the duplicate ``--mon`` row bug: before this
    fix, a settled monitor's stale workflow_state.json row survived
    alongside the done-marker row because the done marker had no
    project_file to key dedup on, producing two rows for one artifact
    directory and losing get_artifacts_dir() on the correct one.
    """
    projects_root = sase_projects_dir()
    artifact_dir = projects_root / "sase" / "artifacts" / "ace-run" / "20260812090000"
    artifact_dir.mkdir(parents=True)
    project_file = str(projects_root / "sase" / "sase.sase")

    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(projects_root),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[
            AgentArtifactRecordWire(
                project_name="sase",
                project_dir=str(projects_root / "sase"),
                project_file=project_file,
                workflow_dir_name="ace-run",
                artifact_dir=str(artifact_dir),
                timestamp="20260812090000",
                workflow_state=WorkflowStateWire(
                    workflow_name="run",
                    status="running",
                    pid=999999,
                    appears_as_agent=True,
                ),
                done=DoneMarkerWire(
                    outcome="monitored",
                    cl_name="sase-l3.1--mon",
                    monitor_state="completed",
                    status_label="MONITORED",
                ),
                has_done_marker=True,
            )
        ],
    )

    agents = load_all_agents(patch_snapshot=[], artifact_snapshot=snapshot)

    assert len(agents) == 1
    (agent,) = agents
    assert agent.status == "MONITORED"
    assert agent.status_bucket == "Done"
    assert get_artifacts_dir(agent) == str(artifact_dir)

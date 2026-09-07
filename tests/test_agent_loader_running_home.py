"""Tests for home running-agent snapshot and resolved-record loading."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models._loaders._running_loaders import (
    ResolvedRunningHomeAgentRecord,
    RunningAgentContentHandle,
    load_running_home_agents,
    load_running_home_agents_from_resolved_records,
    load_running_home_agents_from_snapshot,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    RunningMarkerWire,
)


def test_load_running_home_snapshot_starts_without_run_timestamp() -> None:
    """Home running.json snapshot rows also load as STARTING until RUN is recorded."""
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/.sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[
            AgentArtifactRecordWire(
                project_name="home",
                project_dir="/tmp/.sase/projects/home",
                project_file="/tmp/.sase/projects/home/home.sase",
                workflow_dir_name="ace-run",
                artifact_dir="/tmp/.sase/projects/home/artifacts/ace-run/20260512123456",
                timestamp="20260512123456",
                agent_meta=AgentMetaWire(name="home_runner"),
                running=RunningMarkerWire(pid=1234, cl_name="~"),
            )
        ],
    )

    with patch(
        "sase.ace.tui.models._loaders._running_loaders.is_process_running",
        return_value=True,
    ):
        agents = load_running_home_agents_from_snapshot(snapshot)

    assert len(agents) == 1
    assert agents[0].status == "STARTING"


def test_remote_resolved_running_home_record_has_no_local_effects() -> None:
    """Remote-origin resolved records render without local process/path effects."""
    record = ResolvedRunningHomeAgentRecord(
        origin="remote",
        content_handle=RunningAgentContentHandle(
            origin="remote",
            opaque_id="fleet:apollo:remote_runner",
        ),
        project_file="remote:apollo/home",
        timestamp="20260512123456",
        cl_name="remote_feature",
        model="gpt-5",
        llm_provider="codex",
        vcs_provider="GitHub",
        agent_meta=AgentMetaWire(
            name="remote_runner",
            run_started_at="2026-05-12T12:35:00Z",
        ),
    )

    with (
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            side_effect=AssertionError("remote render checked a local PID"),
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.release_workspace",
            side_effect=AssertionError("remote render released a local workspace"),
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=AssertionError("remote render updated the local index"),
        ),
        patch(
            "pathlib.Path.open",
            side_effect=AssertionError("remote render opened a local path"),
        ),
        patch(
            "pathlib.Path.unlink",
            side_effect=AssertionError("remote render unlinked a local path"),
        ),
    ):
        agents = load_running_home_agents_from_resolved_records([record])

    assert len(agents) == 1
    assert agents[0].agent_name == "remote_runner"
    assert agents[0].status == "RUNNING"
    assert agents[0].pid is None
    assert agents[0].workspace_dir is None
    assert agents[0].index_record_dir is None


def test_remote_resolved_running_home_record_rejects_local_capabilities() -> None:
    with patch("pathlib.Path.open", side_effect=AssertionError("no path reads")):
        with patch("pathlib.Path.unlink", side_effect=AssertionError("no path writes")):
            with patch(
                "sase.ace.tui.models._loaders._running_loaders.is_process_running",
                side_effect=AssertionError("no process checks"),
            ):
                try:
                    RunningAgentContentHandle(
                        origin="remote",
                        opaque_id="fleet:apollo:bad",
                        local_artifact_dir="/tmp/local-artifact",
                    )
                except ValueError as error:
                    assert "local paths" in str(error)
                else:
                    raise AssertionError("remote handle exposed a local path")

                handle = RunningAgentContentHandle(
                    origin="remote",
                    opaque_id="fleet:apollo:bad-pid",
                )
                try:
                    ResolvedRunningHomeAgentRecord(
                        origin="remote",
                        content_handle=handle,
                        project_file="remote:apollo/home",
                        timestamp="20260512123456",
                        cl_name="remote_feature",
                        pid=1234,
                    )
                except ValueError as error:
                    assert "PIDs" in str(error)
                else:
                    raise AssertionError("remote record exposed a PID")


def test_load_running_home_snapshot_stale_marker_refreshes_artifact_index(
    tmp_path: Path,
) -> None:
    artifact_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / "20260512123456"
    )
    artifact_dir.mkdir(parents=True)
    running_file = artifact_dir / "running.json"
    running_file.write_text(json.dumps({"pid": 1234}), encoding="utf-8")
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(tmp_path / ".sase" / "projects"),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[
            AgentArtifactRecordWire(
                project_name="home",
                project_dir=str(tmp_path / ".sase" / "projects" / "home"),
                project_file=str(
                    tmp_path / ".sase" / "projects" / "home" / "home.sase"
                ),
                workflow_dir_name="ace-run",
                artifact_dir=str(artifact_dir),
                timestamp="20260512123456",
                agent_meta=AgentMetaWire(name="home_runner"),
                running=RunningMarkerWire(pid=1234, cl_name="~"),
            )
        ],
    )

    with (
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders."
            "update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        agents = load_running_home_agents_from_snapshot(snapshot)

    assert agents == []
    assert not running_file.exists()
    update_index.assert_called_once_with(artifact_dir)


def test_load_running_home_filesystem_stale_marker_refreshes_artifact_index(
    tmp_path: Path,
) -> None:
    artifact_dir = (
        tmp_path
        / ".sase"
        / "projects"
        / "home"
        / "artifacts"
        / "ace-run"
        / "20260512123456"
    )
    artifact_dir.mkdir(parents=True)
    running_file = artifact_dir / "running.json"
    running_file.write_text(json.dumps({"pid": 1234}), encoding="utf-8")

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders."
            "update_agent_artifact_index_for_marker_mutation"
        ) as update_index,
    ):
        agents = load_running_home_agents()

    assert agents == []
    assert not running_file.exists()
    update_index.assert_called_once_with(artifact_dir)

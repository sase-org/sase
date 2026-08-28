"""Tests for load_all_agents agents derived from RUNNING claim entries."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.ace.agent_tribes import REVIEW_AGENT_TRIBE
from sase.ace.tui.models._loaders._running_loaders import (
    load_agents_from_running_field,
    load_running_home_agents,
    load_running_home_agents_from_snapshot,
)
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    RunningMarkerWire,
)
from tests._agent_loader_helpers import _empty_artifact_snapshot


def test_load_agents_from_running_field_starts_without_run_timestamp() -> None:
    """RUNNING-field claims are liveness claims and load as STARTING."""
    claim = SimpleNamespace(
        workspace_num=1,
        workflow="crs",
        cl_name="my_feature",
        pid=1234,
        artifacts_timestamp="20260512123456",
    )

    with (
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=True,
        ),
    ):
        agents = load_agents_from_running_field(
            ["/tmp/.sase/projects/myproj/myproj.sase"],
            bug_by_cl_name={},
            cl_by_cl_name={},
        )

    assert len(agents) == 1
    assert agents[0].status == "STARTING"


def test_load_agents_from_running_field_releases_dead_claim() -> None:
    """Dead RUNNING-field claims do not render as stuck STARTING agents."""
    claim = SimpleNamespace(
        workspace_num=11,
        workflow="ace(run)-260512_123456",
        cl_name="my_feature",
        pid=1234,
        artifacts_timestamp="20260512123456",
        pinned=False,
    )
    project_file = "/tmp/.sase/projects/myproj/myproj.sase"

    with (
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.release_workspace",
        ) as release,
    ):
        agents = load_agents_from_running_field(
            [project_file],
            bug_by_cl_name={},
            cl_by_cl_name={},
        )

    assert agents == []
    release.assert_called_once_with(
        project_file, 11, claim.workflow, "my_feature", caller_tag="ace-agents-loader"
    )


def test_load_agents_from_running_field_holds_pending_gate_claim() -> None:
    """A pending gate shell's dead-PID claim survives an Agents-tab refresh."""
    claim = SimpleNamespace(
        workspace_num=10,
        workflow="ace-gate",
        cl_name="my_feature",
        pid=1234,
        artifacts_timestamp="20260512123456",
        pinned=False,
    )
    project_file = "/tmp/.sase/projects/myproj/myproj.sase"

    with (
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20260512123456"),
        ),
        patch(
            "sase.gate_shell.store.read_gate_shell_marker",
            return_value=MagicMock(is_terminal=False),
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.release_workspace",
        ) as release,
    ):
        agents = load_agents_from_running_field(
            [project_file],
            bug_by_cl_name={},
            cl_by_cl_name={},
        )

    assert agents == []
    release.assert_not_called()


def test_load_agents_from_running_field_releases_settled_gate_claim() -> None:
    """The same claim is reaped once the gate shell's marker turns terminal."""
    claim = SimpleNamespace(
        workspace_num=10,
        workflow="ace-gate",
        cl_name="my_feature",
        pid=1234,
        artifacts_timestamp="20260512123456",
        pinned=False,
    )
    project_file = "/tmp/.sase/projects/myproj/myproj.sase"

    with (
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
            return_value=Path("/tmp/artifacts/20260512123456"),
        ),
        patch(
            "sase.gate_shell.store.read_gate_shell_marker",
            return_value=MagicMock(is_terminal=True),
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.release_workspace",
        ) as release,
    ):
        agents = load_agents_from_running_field(
            [project_file],
            bug_by_cl_name={},
            cl_by_cl_name={},
        )

    assert agents == []
    release.assert_called_once_with(
        project_file, 10, "ace-gate", "my_feature", caller_tag="ace-agents-loader"
    )


def test_load_agents_from_running_field_keeps_live_deferred_claim() -> None:
    """Deferred #0 claims are visible while their runner PID is alive."""
    claim = SimpleNamespace(
        workspace_num=0,
        workflow="ace(run)-260512_123456",
        cl_name="my_feature",
        pid=1234,
        artifacts_timestamp="20260512123456",
        pinned=False,
    )

    with (
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.release_workspace",
        ) as release,
    ):
        agents = load_agents_from_running_field(
            ["/tmp/.sase/projects/myproj/myproj.sase"],
            bug_by_cl_name={},
            cl_by_cl_name={},
        )

    assert len(agents) == 1
    assert agents[0].workspace_num == 0
    release.assert_not_called()


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


def test_load_all_agents_with_running_claims() -> None:
    """Test load_all_agents with RUNNING field claims."""
    mock_claim = MagicMock()
    mock_claim.workspace_num = 1
    mock_claim.workflow = "crs"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = 12345
    mock_claim.artifacts_timestamp = None

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.sase"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=True,
        ),
        patch("sase.ace.tui.models.agent_loader.is_process_running", return_value=True),
        patch("sase.ace.tui.models.agent_loader.find_all_patches", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
    ):
        agents = load_all_agents()
        assert len(agents) == 1
        assert agents[0].agent_type == AgentType.RUNNING
        assert agents[0].status == "STARTING"
        assert agents[0].cl_name == "my_feature"
        assert agents[0].workspace_num == 1
        assert agents[0].workflow == "crs"


def test_load_all_agents_filters_hook_processes() -> None:
    """Test that RUNNING entries with axe(hooks) workflow are filtered out."""
    # Mock a RUNNING claim with axe(hooks)-1 workflow (hook process, not agent)
    mock_claim = MagicMock()
    mock_claim.workspace_num = 100
    mock_claim.workflow = "axe(hooks)-1"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = 12345
    mock_claim.artifacts_timestamp = None

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.sase"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=True,
        ),
        patch("sase.ace.tui.models.agent_loader.is_process_running", return_value=True),
        patch("sase.ace.tui.models.agent_loader.find_all_patches", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
    ):
        agents = load_all_agents()
        # Hook process should be filtered out
        assert len(agents) == 0


def test_load_all_agents_filters_operational_lease_claims() -> None:
    """Machine-owned operational leases are not agents and render no row."""
    # Mock a live lease claim taken by the bead_claim_checks chop.
    mock_claim = MagicMock()
    mock_claim.workspace_num = 100
    mock_claim.workflow = "lease(chop:bead_claim_checks)"
    mock_claim.cl_name = "bead_claim_checks:demo"
    mock_claim.pid = 12345
    mock_claim.artifacts_timestamp = None

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.sase"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=True,
        ),
        patch("sase.ace.tui.models.agent_loader.is_process_running", return_value=True),
        patch("sase.ace.tui.models.agent_loader.find_all_patches", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
    ):
        agents = load_all_agents()
        assert len(agents) == 0


def test_load_agents_from_running_field_releases_dead_lease_claim() -> None:
    """The lease skip stays below the stale-claim gate, so dead leases are reaped."""
    claim = SimpleNamespace(
        workspace_num=100,
        workflow="lease(chop:bead_claim_checks)",
        cl_name="bead_claim_checks:demo",
        pid=12345,
        artifacts_timestamp=None,
        pinned=False,
    )
    project_file = "/tmp/.sase/projects/myproj/myproj.sase"

    with (
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.release_workspace",
        ) as release,
    ):
        agents = load_agents_from_running_field(
            [project_file],
            bug_by_cl_name={},
            cl_by_cl_name={},
        )

    assert agents == []
    release.assert_called_once_with(
        project_file,
        100,
        claim.workflow,
        "bead_claim_checks:demo",
        caller_tag="ace-agents-loader",
    )


def test_load_all_agents_includes_axe_fix_hook() -> None:
    """Test that RUNNING entries with axe(fix-hook) workflow are included."""
    # Mock a RUNNING claim with axe(fix-hook)-timestamp workflow
    mock_claim = MagicMock()
    mock_claim.workspace_num = 100
    mock_claim.workflow = "axe(fix-hook)-251230_151429"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = 12345
    mock_claim.artifacts_timestamp = "20251230151429"

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.sase"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=True,
        ),
        patch("sase.ace.tui.models.agent_loader.is_process_running", return_value=True),
        patch("sase.ace.tui.models.agent_loader.find_all_patches", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
    ):
        agents = load_all_agents()
        # Agent workflow should be included
        assert len(agents) == 1
        assert agents[0].agent_type == AgentType.RUNNING
        assert agents[0].workflow == "axe(fix-hook)-251230_151429"
        assert agents[0].hidden is False
        assert agents[0].tribe == REVIEW_AGENT_TRIBE


def test_load_all_agents_assigns_axe_summarize_hook_to_review_tribe() -> None:
    """RUNNING entries with axe(summarize-hook) join the review tribe."""
    mock_claim = MagicMock()
    mock_claim.workspace_num = 100
    mock_claim.workflow = "axe(summarize-hook)-251230_151429"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = 12345
    mock_claim.artifacts_timestamp = "20251230151429"

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.sase"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=True,
        ),
        patch("sase.ace.tui.models.agent_loader.is_process_running", return_value=True),
        patch("sase.ace.tui.models.agent_loader.find_all_patches", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
    ):
        agents = load_all_agents()
        assert len(agents) == 1
        assert agents[0].agent_type == AgentType.RUNNING
        assert agents[0].workflow == "axe(summarize-hook)-251230_151429"
        assert agents[0].hidden is False
        assert agents[0].tribe == REVIEW_AGENT_TRIBE

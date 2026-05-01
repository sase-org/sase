"""Tests for load_all_agents agents derived from Rust compose inputs."""

from dataclasses import replace
from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_loader import (
    _collect_compose_input_pids,
    load_all_agents,
)
from sase.ace.tui.actions.agents._loading_helpers import load_agents_from_disk
from sase.core.agent_compose_wire import (
    AgentComposeInputWire,
    AgentWire,
    ComposedAgentListWire,
    RunningClaimWire,
)
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    RunningMarkerWire,
    WorkflowStateWire,
)
from sase.core.wire import (
    ChangeSpecWire,
    CommentWire,
    HookStatusLineWire,
    HookWire,
    SourceSpanWire,
)
from tests._agent_loader_helpers import _empty_artifact_snapshot


def test_collect_compose_input_pids_covers_wire_sources() -> None:
    snapshot = replace(
        _empty_artifact_snapshot(),
        records=[
            AgentArtifactRecordWire(
                project_name="demo",
                project_dir="/tmp/sase/projects/demo",
                project_file="/tmp/sase/projects/demo/demo.gp",
                workflow_dir_name="ace-run",
                artifact_dir="/tmp/sase/projects/demo/artifacts/ace-run/ts",
                timestamp="20260501120000",
                running=RunningMarkerWire(pid=202),
                workflow_state=WorkflowStateWire(
                    workflow_name="deploy",
                    status="running",
                    pid=303,
                ),
            )
        ],
    )
    changespec = ChangeSpecWire(
        schema_version=1,
        name="demo",
        project_basename="demo",
        file_path="/tmp/sase/projects/demo/demo.gp",
        source_span=SourceSpanWire(
            file_path="/tmp/sase/projects/demo/demo.gp",
            start_line=1,
            end_line=10,
        ),
        status="Ready",
        parent=None,
        cl_or_pr=None,
        bug=None,
        description="",
        hooks=[
            HookWire(
                command="just test",
                status_lines=[
                    HookStatusLineWire(
                        commit_entry_num="1",
                        timestamp="20260501_120000",
                        status="RUNNING",
                        suffix="fix_hook-404-260501_120000",
                        suffix_type="running_agent",
                    )
                ],
            )
        ],
        comments=[
            CommentWire(
                reviewer="cr",
                file_path="/tmp/comments.json",
                suffix="crs-505-260501_120500",
                suffix_type="running_agent",
            )
        ],
    )

    pids = _collect_compose_input_pids(
        AgentComposeInputWire(
            artifact_scan=snapshot,
            running_claims=[
                RunningClaimWire(
                    project_file="/tmp/sase/projects/demo/demo.gp",
                    project_name="demo",
                    cl_name="demo",
                    pid=101,
                )
            ],
            changespecs=[changespec],
        )
    )

    assert pids == {101, 202, 303, 404, 505}


def test_load_all_agents_with_running_claims() -> None:
    """Test load_all_agents sends RUNNING claims through Rust composition."""
    mock_claim = MagicMock()
    mock_claim.workspace_num = 1
    mock_claim.workflow = "crs"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = None
    mock_claim.artifacts_timestamp = "20260501120000"

    def fake_rust_compose(input_wire):
        claim = input_wire.running_claims[0]
        return ComposedAgentListWire(
            agents=[
                AgentWire(
                    agent_type="run",
                    cl_name=claim.cl_name,
                    project_file=claim.project_file,
                    status="RUNNING",
                    workspace_num=claim.workspace_num,
                    workflow=claim.workflow,
                    raw_suffix=claim.raw_suffix,
                )
            ]
        )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch("sase.ace.tui.models.agent_loader.find_all_changespecs", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch("sase.core.agent_compose_facade.compose_agent_list", fake_rust_compose),
    ):
        agents = load_all_agents()
        assert len(agents) == 1
        assert agents[0].agent_type == AgentType.RUNNING
        assert agents[0].cl_name == "my_feature"
        assert agents[0].workspace_num == 1
        assert agents[0].workflow == "crs"


def test_load_all_agents_collects_liveness_without_python_candidate_loaders() -> None:
    """The Rust route does not build the old Python candidate list first."""
    mock_claim = MagicMock()
    mock_claim.workspace_num = 1
    mock_claim.workflow = "crs"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = 12345
    mock_claim.artifacts_timestamp = "20260501120000"
    captured = []

    def fake_rust_compose(input_wire):
        captured.append(input_wire)
        return ComposedAgentListWire(
            agents=[
                AgentWire(
                    agent_type="run",
                    cl_name="my_feature",
                    project_file="/tmp/test.gp",
                    status="RUNNING",
                    raw_suffix="20260501120000",
                    pid=12345,
                )
            ]
        )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch("sase.ace.tui.models.agent_loader.find_all_changespecs", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models._loaders._done_loaders.load_done_agents_from_snapshot",
            side_effect=AssertionError("Python done loader should not run"),
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.load_running_home_agents_from_snapshot",
            side_effect=AssertionError("Python running-home loader should not run"),
        ),
        patch(
            "sase.ace.tui.models._loaders._workflow_snapshot_loaders.load_workflow_agents_from_snapshot",
            side_effect=AssertionError("Python workflow loader should not run"),
        ),
        patch(
            "sase.ace.tui.models._loaders._workflow_snapshot_loaders.load_workflow_agent_steps_from_snapshot",
            side_effect=AssertionError("Python workflow-step loader should not run"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.core.agent_compose_facade.compose_agent_list",
            side_effect=fake_rust_compose,
        ),
    ):
        agents = load_all_agents()

    assert len(agents) == 1
    assert len(captured) == 1
    compose_input = captured[0]
    assert compose_input.running_claims[0].pid == 12345
    assert compose_input.running_claims[0].raw_suffix == "20260501120000"
    assert compose_input.alive_pids == [12345]


def test_load_all_agents_default_rust_backend_returns_rehydrated_agents() -> None:
    """Default Rust backend returns normal Agent objects for downstream TUI code."""
    captured = []

    def fake_rust_compose(input_wire):
        captured.append(input_wire)
        return ComposedAgentListWire(
            agents=[
                AgentWire(
                    agent_type="run",
                    cl_name="my_feature",
                    project_file="/tmp/test.gp",
                    status="RUNNING",
                    raw_suffix="20260501120000",
                    pid=12345,
                )
            ]
        )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[],
        ),
        patch("sase.ace.tui.models.agent_loader.find_all_changespecs", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.core.agent_compose_facade.compose_agent_list",
            side_effect=fake_rust_compose,
        ),
    ):
        agents = load_all_agents()

    assert len(captured) == 1
    assert agents[0].agent_type == AgentType.RUNNING
    assert agents[0].identity == (AgentType.RUNNING, "my_feature", "20260501120000")
    assert agents[0].status == "RUNNING"
    assert agents[0].pid == 12345


def test_load_agents_from_disk_preserves_rust_dismissed_rows() -> None:
    """The TUI loader keeps Rust-composed dismissed rows for cleanup/revive."""
    dismissed_wire = AgentWire(
        agent_type="run",
        cl_name="my_feature",
        project_file="/tmp/test.gp",
        status="DONE",
        raw_suffix="20260501123000",
    )

    def fake_rust_compose(_input_wire):
        return ComposedAgentListWire(
            agents=[],
            dismissed_from_loader=[dismissed_wire],
        )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[],
        ),
        patch("sase.ace.tui.models.agent_loader.find_all_changespecs", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.agent_tags.load_agent_tags",
            return_value={},
        ),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
            ".dismissed_bundles",
            return_value=[],
        ),
        patch(
            "sase.core.agent_compose_facade.compose_agent_list",
            side_effect=fake_rust_compose,
        ),
    ):
        agents, dismissed = load_agents_from_disk(
            {(AgentType.RUNNING, "my_feature", "20260501123000")}
        )

    assert agents == []
    assert [agent.identity for agent in dismissed] == [
        (AgentType.RUNNING, "my_feature", "20260501123000")
    ]


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
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch("sase.ace.tui.models.agent_loader.find_all_changespecs", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
    ):
        agents = load_all_agents()
        # Hook process should be filtered out
        assert len(agents) == 0


def test_load_all_agents_includes_axe_fix_hook() -> None:
    """Test that RUNNING entries with axe(fix-hook) workflow are included."""
    # Mock a RUNNING claim with axe(fix-hook)-timestamp workflow
    mock_claim = MagicMock()
    mock_claim.workspace_num = 100
    mock_claim.workflow = "axe(fix-hook)-251230_151429"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = None  # No PID to skip process check
    mock_claim.artifacts_timestamp = "20251230151429"

    with (
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=["/tmp/test.gp"],
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.get_claimed_workspaces",
            return_value=[mock_claim],
        ),
        patch("sase.ace.tui.models.agent_loader.find_all_changespecs", return_value=[]),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
    ):
        agents = load_all_agents()
        # Agent workflow should be included
        assert len(agents) == 1
        assert agents[0].agent_type == AgentType.RUNNING
        assert agents[0].workflow == "axe(fix-hook)-251230_151429"

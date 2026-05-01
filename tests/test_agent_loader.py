"""Tests for load_all_agents agents derived from RUNNING claim entries."""

from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from sase.ace.tui.actions.agents._loading_helpers import load_agents_from_disk
from sase.core.agent_compose_wire import AgentWire, ComposedAgentListWire
from tests._agent_loader_helpers import _empty_artifact_snapshot


def test_load_all_agents_with_running_claims() -> None:
    """Test load_all_agents with RUNNING field claims."""
    mock_claim = MagicMock()
    mock_claim.workspace_num = 1
    mock_claim.workflow = "crs"
    mock_claim.cl_name = "my_feature"

    with (
        patch.dict("os.environ", {"SASE_AGENT_COMPOSE_BACKEND": "python"}),
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
        assert agents[0].cl_name == "my_feature"
        assert agents[0].workspace_num == 1
        assert agents[0].workflow == "crs"


def test_load_all_agents_shadow_collects_compose_input() -> None:
    """Opt-in shadow mode calls Rust with the collected compose input."""
    mock_claim = MagicMock()
    mock_claim.workspace_num = 1
    mock_claim.workflow = "crs"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = 12345
    mock_claim.artifacts_timestamp = "20260501120000"
    captured = []

    def fake_rust_compose(input_wire):
        captured.append(input_wire)
        return ComposedAgentListWire()

    with (
        patch.dict(
            "os.environ",
            {"SASE_AGENT_COMPOSE_BACKEND": "python", "SASE_AGENT_COMPOSE_SHADOW": "1"},
        ),
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


def test_load_all_agents_python_backend_is_explicit_reference_route() -> None:
    """The legacy composer is still available only through an explicit switch."""
    mock_claim = MagicMock()
    mock_claim.workspace_num = 1
    mock_claim.workflow = "crs"
    mock_claim.cl_name = "my_feature"
    mock_claim.pid = None
    mock_claim.artifacts_timestamp = "20260501120000"

    with (
        patch.dict("os.environ", {"SASE_AGENT_COMPOSE_BACKEND": "python"}),
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
        patch(
            "sase.core.agent_compose_facade.compose_agent_list",
            side_effect=AssertionError("rust composer should not run"),
        ),
    ):
        agents = load_all_agents()

    assert [agent.identity for agent in agents] == [
        (AgentType.RUNNING, "my_feature", "20260501120000")
    ]


def test_load_all_agents_rejects_unknown_compose_backend() -> None:
    with patch.dict("os.environ", {"SASE_AGENT_COMPOSE_BACKEND": "bogus"}):
        try:
            load_all_agents()
        except ValueError as exc:
            assert "SASE_AGENT_COMPOSE_BACKEND" in str(exc)
        else:  # pragma: no cover - assertion guard
            raise AssertionError("expected ValueError")


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

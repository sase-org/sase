"""Tests for load_all_agents agents derived from RUNNING claim entries."""

from unittest.mock import MagicMock, patch

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from sase.core.agent_compose_wire import ComposedAgentListWire
from tests._agent_loader_helpers import _empty_artifact_snapshot


def test_load_all_agents_with_running_claims() -> None:
    """Test load_all_agents with RUNNING field claims."""
    mock_claim = MagicMock()
    mock_claim.workspace_num = 1
    mock_claim.workflow = "crs"
    mock_claim.cl_name = "my_feature"

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
        patch.dict("os.environ", {"SASE_AGENT_COMPOSE_SHADOW": "1"}),
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

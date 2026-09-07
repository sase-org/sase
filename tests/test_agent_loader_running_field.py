"""Tests for load_agents_from_running_field RUNNING-claim handling."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.ace.tui.models._loaders._running_loaders import load_agents_from_running_field


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
    """A pending gate shell's dead-PID claim survives an Agents-tab refresh.

    The claim itself contributes no row: the gate-shell member renders from
    its own artifact record. See
    ``tests/test_agent_loader_pending_gate_shell.py`` for the row-producing
    counterpart.
    """
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

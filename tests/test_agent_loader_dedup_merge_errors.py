"""Tests for agent dedup error merging (recorded vs synthetic fallback errors)."""

from sase.ace.tui.models._dedup import dedup_running_vs_workflow
from sase.ace.tui.models.agent import Agent, AgentType


def test_dedup_recorded_error_beats_synthetic_fallback() -> None:
    """A done.json recorded error replaces the synthesized fallback error.

    When the WORKFLOW row carries the "Runner exited without recording an
    error" fallback (marked synthetic at load time) and the done.json
    RUNNING row carries the real setup failure, the merged row must show
    the recorded error.
    """
    project = "/tmp/test.sase"
    suffix = "20260101140000"
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file=project,
        status="FAILED",
        start_time=None,
        workflow="ace(run)",
        raw_suffix=suffix,
        error_message=(
            "Runner exited without recording an error "
            "(crash, kill, or startup failure).\nLast output:\nstdout tail"
        ),
        error_is_synthetic=True,
    )
    done_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file=project,
        status="FAILED",
        start_time=None,
        workflow="ace-run",
        raw_suffix=suffix,
        error_message="_WorkspaceBeadEvictionRefused: bead store has unpublished commits",
    )

    result = dedup_running_vs_workflow([workflow_agent, done_agent])

    assert len(result) == 1
    assert (
        result[0].error_message
        == "_WorkspaceBeadEvictionRefused: bead store has unpublished commits"
    )
    assert result[0].error_is_synthetic is False


def test_dedup_recorded_workflow_error_not_replaced_by_done_error() -> None:
    """A recorded WORKFLOW error still wins over a done.json error."""
    project = "/tmp/test.sase"
    suffix = "20260101140001"
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file=project,
        status="FAILED",
        start_time=None,
        workflow="ace(run)",
        raw_suffix=suffix,
        error_message="Step 'run' failed: exit 1",
    )
    done_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file=project,
        status="FAILED",
        start_time=None,
        workflow="ace-run",
        raw_suffix=suffix,
        error_message="Agent exited before completion",
    )

    result = dedup_running_vs_workflow([workflow_agent, done_agent])

    assert len(result) == 1
    assert result[0].error_message == "Step 'run' failed: exit 1"
    assert result[0].error_is_synthetic is False


def test_dedup_synthetic_fallback_survives_without_recorded_error() -> None:
    """The fallback stays when the done.json row records no error."""
    project = "/tmp/test.sase"
    suffix = "20260101140002"
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file=project,
        status="FAILED",
        start_time=None,
        workflow="ace(run)",
        raw_suffix=suffix,
        error_message="Runner exited without recording an error.",
        error_is_synthetic=True,
    )
    done_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file=project,
        status="FAILED",
        start_time=None,
        workflow="ace-run",
        raw_suffix=suffix,
    )

    result = dedup_running_vs_workflow([workflow_agent, done_agent])

    assert len(result) == 1
    assert result[0].error_message == "Runner exited without recording an error."
    assert result[0].error_is_synthetic is True

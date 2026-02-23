"""Tests for workflow state and step loaders."""

from unittest.mock import patch

from sase.ace.tui.models._loaders._workflow_loaders import load_workflow_agents


def test_step_output_none_when_no_steps() -> None:
    """Verify step_output is None when workflow has no steps."""
    from sase.ace.tui.models.workflow import WorkflowEntry

    entry = WorkflowEntry(
        workflow_name="test-workflow",
        cl_name="test_cl",
        project_file="/fake/path.gp",
        status="DONE",
        current_step=0,
        total_steps=0,
        steps=[],
        start_time=None,
        artifacts_dir="/tmp/fake",
        appears_as_agent=False,
        is_anonymous=False,
    )

    with patch(
        "sase.ace.tui.models._loaders._workflow_loaders.load_workflow_states",
        return_value=[entry],
    ):
        agents = load_workflow_agents()

    assert len(agents) == 1
    assert agents[0].step_output is None

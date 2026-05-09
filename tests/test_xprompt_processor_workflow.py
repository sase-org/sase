"""Tests for WorkflowResult."""

from sase.xprompt.workflow_runner import WorkflowResult


def test_workflow_result_construction() -> None:
    """Test basic WorkflowResult dataclass construction."""
    result = WorkflowResult(
        output='{"key": "value"}',
        response_text="Some response",
        artifacts_dir="/tmp/artifacts",
    )
    assert result.output == '{"key": "value"}'
    assert result.response_text == "Some response"
    assert result.artifacts_dir == "/tmp/artifacts"


def test_workflow_result_none_response_text() -> None:
    """Test WorkflowResult with None response_text."""
    result = WorkflowResult(output="", response_text=None, artifacts_dir="/tmp/x")
    assert result.response_text is None

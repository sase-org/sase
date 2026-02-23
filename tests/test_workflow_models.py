"""Tests for Workflow model methods."""

from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep

# ============================================================================
# Workflow.appears_as_agent() tests
# ============================================================================


# ============================================================================
# Workflow.is_simple_xprompt() tests
# ============================================================================


def test_workflow_is_simple_xprompt_with_inputs() -> None:
    """Test that single prompt_part with inputs is still simple xprompt."""
    workflow = Workflow(
        name="review",
        inputs=[InputArg(name="code", type=InputType.TEXT)],
        steps=[
            WorkflowStep(name="main", prompt_part="Review: {{ code }}"),
        ],
    )
    assert workflow.is_simple_xprompt() is True


# ============================================================================
# Workflow.is_anonymous() tests
# ============================================================================

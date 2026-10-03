"""Tests for Workflow model methods."""

from sase.macro.models import InputArg, InputType
from sase.macro.workflow_models import Workflow, WorkflowStep

# ============================================================================
# Workflow.appears_as_agent() tests
# ============================================================================


# ============================================================================
# Workflow.is_simple_macro() tests
# ============================================================================


def test_workflow_is_simple_macro_with_inputs() -> None:
    """Test that single prompt_part with inputs is still simple macro."""
    workflow = Workflow(
        name="review",
        inputs=[InputArg(name="code", type=InputType.TEXT)],
        steps=[
            WorkflowStep(name="main", prompt_part="Review: {{ code }}"),
        ],
    )
    assert workflow.is_simple_macro() is True


# ============================================================================
# Workflow.is_anonymous() tests
# ============================================================================

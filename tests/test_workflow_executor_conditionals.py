"""Tests for conditional execution in workflow_executor."""

import os
import tempfile
from typing import Any

from sase.xprompt.workflow_executor import WorkflowExecutor
from sase.xprompt.workflow_models import (
    StepStatus,
    Workflow,
    WorkflowStep,
)


def _create_workflow(
    name: str,
    steps: list[WorkflowStep],
) -> Workflow:
    """Helper to create a workflow for testing."""
    return Workflow(name=name, steps=steps)


def _create_executor(
    workflow: Workflow,
    args: dict[str, Any] | None = None,
) -> WorkflowExecutor:
    """Helper to create an executor with a temp artifacts dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifacts_dir = os.path.join(tmpdir, "artifacts")
        os.makedirs(artifacts_dir, exist_ok=True)
        executor = WorkflowExecutor(
            workflow=workflow,
            args=args or {},
            artifacts_dir=artifacts_dir,
        )
        # Store tmpdir reference to keep it alive during test
        executor._test_tmpdir = tmpdir  # type: ignore[attr-defined]
        return executor


# ============================================================================
# TestIfCondition - if: condition evaluation
# ============================================================================


def test_if_condition_true_executes_step() -> None:
    """Test that if: true executes the step."""
    steps = [
        WorkflowStep(
            name="conditional",
            bash="echo success",
            condition="{{ do_run }}",
        ),
    ]
    workflow = _create_workflow("test", steps)
    executor = _create_executor(workflow, {"do_run": True})

    success = executor.execute()

    assert success
    assert executor.state.steps[0].status == StepStatus.COMPLETED


def test_if_condition_empty_string_skips() -> None:
    """Test that empty string evaluates to false."""
    steps = [
        WorkflowStep(
            name="conditional",
            bash="echo should_skip",
            condition="{{ value }}",
        ),
    ]
    workflow = _create_workflow("test", steps)
    executor = _create_executor(workflow, {"value": ""})

    success = executor.execute()

    assert success
    assert executor.state.steps[0].status == StepStatus.SKIPPED


# ============================================================================
# TestEvaluateCondition - _evaluate_condition method
# ============================================================================


# ============================================================================
# TestCombinedControlFlow - combinations of if: with for:
# ============================================================================

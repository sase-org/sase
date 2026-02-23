"""Tests for parallel execution in workflow_executor."""

import os
import tempfile
from typing import Any
from unittest.mock import patch

import pytest
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_executor import WorkflowExecutor
from sase.xprompt.workflow_models import (
    ParallelConfig,
    Workflow,
    WorkflowExecutionError,
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
# TestParallelExecution - parallel: step execution
# ============================================================================


def test_parallel_with_join_array() -> None:
    """Test parallel with join: array."""
    nested_steps = [
        WorkflowStep(name="step_a", bash='echo "val=1"'),
        WorkflowStep(name="step_b", bash='echo "val=2"'),
    ]
    steps = [
        WorkflowStep(
            name="parallel_test",
            parallel_config=ParallelConfig(steps=nested_steps),
            join="array",
        ),
    ]
    workflow = _create_workflow("test", steps)
    executor = _create_executor(workflow)

    executor.execute()

    output = executor.context["parallel_test"]
    assert isinstance(output, list)
    assert len(output) == 2


def test_parallel_context_isolation() -> None:
    """Test that parallel steps have isolated context."""
    # Each step tries to modify a shared variable
    # If context is properly isolated, they shouldn't interfere
    nested_steps = [
        WorkflowStep(
            name="step_a",
            bash='echo "result={{ shared_var }}_a"',
        ),
        WorkflowStep(
            name="step_b",
            bash='echo "result={{ shared_var }}_b"',
        ),
    ]
    steps = [
        WorkflowStep(
            name="parallel_test",
            parallel_config=ParallelConfig(steps=nested_steps),
        ),
    ]
    workflow = _create_workflow("test", steps)
    executor = _create_executor(workflow, {"shared_var": "original"})

    success = executor.execute()

    assert success
    output = executor.context["parallel_test"]
    # Both should have seen the original value
    assert output["step_a"]["result"] == "original_a"
    assert output["step_b"]["result"] == "original_b"


def test_parallel_step_failure_raises() -> None:
    """Test that failure in parallel step raises error."""
    nested_steps = [
        WorkflowStep(name="step_a", bash='echo "a=done"'),
        WorkflowStep(name="step_b", bash="exit 1"),  # This will fail
    ]
    steps = [
        WorkflowStep(
            name="parallel_test",
            parallel_config=ParallelConfig(steps=nested_steps),
        ),
    ]
    workflow = _create_workflow("test", steps)
    executor = _create_executor(workflow)

    with pytest.raises(WorkflowExecutionError) as exc_info:
        executor.execute()

    assert "parallel_test" in str(exc_info.value)


# ============================================================================
# TestForParallel - for: + parallel: combination
# ============================================================================


def test_for_parallel_with_join_object() -> None:
    """Test for: + parallel: with join: object."""
    nested_steps = [
        WorkflowStep(name="lint", bash='echo "result=lint_{{ file }}"'),
        WorkflowStep(name="format", bash='echo "result=format_{{ file }}"'),
    ]
    steps = [
        WorkflowStep(
            name="process_files",
            for_loop={"file": "{{ files }}"},
            parallel_config=ParallelConfig(steps=nested_steps),
            join="object",
        ),
    ]
    workflow = _create_workflow("test", steps)
    executor = _create_executor(workflow, {"files": ["a.py", "b.py"]})

    success = executor.execute()

    assert success
    output = executor.context["process_files"]
    # join: object merges all results
    assert isinstance(output, dict)


def test_for_parallel_empty_list() -> None:
    """Test for: + parallel: with empty iteration list."""
    nested_steps = [
        WorkflowStep(name="step_a", bash='echo "a={{ item }}"'),
        WorkflowStep(name="step_b", bash='echo "b={{ item }}"'),
    ]
    steps = [
        WorkflowStep(
            name="process",
            for_loop={"item": "{{ items }}"},
            parallel_config=ParallelConfig(steps=nested_steps),
        ),
    ]
    workflow = _create_workflow("test", steps)
    executor = _create_executor(workflow, {"items": []})

    success = executor.execute()

    assert success
    output = executor.context["process"]
    assert output == []


# ============================================================================
# TestPreExpandParallelEmbeddedWorkflows
# ============================================================================


def test_pre_expand_parallel_no_embedded_workflows() -> None:
    """Test that steps without embedded workflows pass through unchanged."""
    nested_steps = [
        WorkflowStep(name="step_a", bash='echo "a=done"'),
        WorkflowStep(name="step_b", agent="Plain prompt with no refs"),
    ]

    workflow = _create_workflow("test", [])
    executor = _create_executor(workflow)

    with patch("sase.xprompt.loader.get_all_workflows") as mock_get:
        mock_get.return_value = {}
        modified, collected = executor._pre_expand_parallel_embedded_workflows(
            nested_steps
        )

    # Bash step passes through as-is
    assert modified[0] is nested_steps[0]
    # Prompt step without embedded refs also passes through as-is
    assert modified[1] is nested_steps[1]
    assert collected == []


def test_pre_expand_parallel_collects_post_steps() -> None:
    """Test that post-steps are collected for execution after parallel."""
    # Create an embedded workflow with prompt_part + post-step (like #file)
    embedded_wf = Workflow(
        name="test_embed",
        inputs=[InputArg(name="name", type=InputType.WORD)],
        steps=[
            WorkflowStep(
                name="inject",
                prompt_part="Write output to file {{ name }}.md",
            ),
            WorkflowStep(
                name="verify",
                hidden=True,
                bash='echo "verified={{ name }}"',
            ),
        ],
    )

    nested_steps = [
        WorkflowStep(
            name="agent_a", agent="Research topic A. #test_embed(name=topicA)"
        ),
        WorkflowStep(
            name="agent_b", agent="Research topic B. #test_embed(name=topicB)"
        ),
    ]

    workflow = _create_workflow("test", [])
    executor = _create_executor(workflow)

    with patch("sase.xprompt.loader.get_all_workflows") as mock_get:
        mock_get.return_value = {"test_embed": embedded_wf}
        modified, collected = executor._pre_expand_parallel_embedded_workflows(
            nested_steps
        )

    # Both prompts should have prompt_part expanded inline
    assert modified[0].agent is not None
    assert modified[1].agent is not None
    assert "Write output to file" in modified[0].agent
    assert "#test_embed" not in modified[0].agent
    assert "Write output to file" in modified[1].agent
    assert "#test_embed" not in modified[1].agent

    # Original steps should not be mutated
    assert nested_steps[0].agent is not None
    assert nested_steps[1].agent is not None
    assert "#test_embed" in nested_steps[0].agent
    assert "#test_embed" in nested_steps[1].agent

    # Should have collected 2 sets of post-steps (one per embedded ref)
    assert len(collected) == 2
    for info in collected:
        assert len(info.post_steps) == 1
        assert info.post_steps[0].name == "verify"
        assert "name" in info.context


# ============================================================================
# TestParallelStepNumbering - marker files with parent step info
# ============================================================================

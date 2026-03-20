"""Tests for finally step handling in WorkflowExecutor."""

import tempfile

import pytest
from sase.xprompt import WorkflowExecutor
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowExecutionError,
    WorkflowStep,
    WorkflowValidationError,
)
from sase.xprompt.workflow_loader_parse import _parse_workflow_step
from sase.xprompt.workflow_validator import _validate_finally_steps


class TestFinallyStepExecution:
    """Tests for finally step execution in the main executor loop."""

    def test_finally_step_runs_after_failure(self) -> None:
        """Finally step should execute even when a prior step fails."""
        steps = [
            WorkflowStep(name="setup", bash='echo "ready=true"'),
            WorkflowStep(name="fail_step", bash="exit 1"),
            WorkflowStep(
                name="cleanup",
                bash='echo "cleaned=yes"',
                finally_=True,
            ),
        ]
        workflow = Workflow(name="test", steps=steps)

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            with pytest.raises(WorkflowExecutionError):
                executor.execute()

            # The finally step should have run despite the prior failure
            assert "cleanup" in executor.context
            assert executor.context["cleanup"]["cleaned"] == "yes"

    def test_finally_step_runs_after_return_false(self) -> None:
        """Finally step should execute when a prior step returns False (HITL reject)."""
        from unittest.mock import MagicMock

        from sase.xprompt import HITLHandler, HITLResult

        steps = [
            WorkflowStep(
                name="check",
                bash='echo "status=ok"',
                hitl=True,
            ),
            WorkflowStep(
                name="cleanup",
                bash='echo "cleaned=yes"',
                finally_=True,
            ),
        ]
        workflow = Workflow(name="test", steps=steps)

        handler = MagicMock(spec=HITLHandler)
        handler.prompt.return_value = HITLResult(action="reject")

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow,
                args={},
                artifacts_dir=tmpdir,
                hitl_handler=handler,
            )
            result = executor.execute()

            assert result is False
            # Finally step should still have executed
            assert "cleanup" in executor.context
            assert executor.context["cleanup"]["cleaned"] == "yes"

    def test_non_finally_steps_skipped_after_failure(self) -> None:
        """Non-finally steps after a failure should be skipped."""
        steps = [
            WorkflowStep(name="fail_step", bash="exit 1"),
            WorkflowStep(name="should_skip", bash='echo "ran=yes"'),
            WorkflowStep(
                name="cleanup",
                bash='echo "ran=yes"',
                finally_=True,
            ),
        ]
        workflow = Workflow(name="test", steps=steps)

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            with pytest.raises(WorkflowExecutionError):
                executor.execute()

            # The skipped step should have empty context
            assert executor.context.get("should_skip") == {}
            # The finally step should have run
            assert "cleanup" in executor.context
            assert executor.context["cleanup"]["ran"] == "yes"

    def test_no_finally_preserves_original_behavior(self) -> None:
        """Without finally steps, failures should behave exactly as before."""
        steps = [
            WorkflowStep(name="fail_step", bash="exit 1"),
            WorkflowStep(name="never_reached", bash='echo "ran=yes"'),
        ]
        workflow = Workflow(name="test", steps=steps)

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            with pytest.raises(WorkflowExecutionError):
                executor.execute()

            # The second step should NOT be in context (not even as {})
            assert "never_reached" not in executor.context

    def test_all_steps_succeed_with_finally(self) -> None:
        """When all steps succeed, finally steps run normally too."""
        steps = [
            WorkflowStep(name="work", bash='echo "done=true"'),
            WorkflowStep(
                name="cleanup",
                bash='echo "cleaned=yes"',
                finally_=True,
            ),
        ]
        workflow = Workflow(name="test", steps=steps)

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            result = executor.execute()

            assert result is True
            assert executor.context["cleanup"]["cleaned"] == "yes"

    def test_finally_step_with_if_condition(self) -> None:
        """Finally steps with if: conditions should respect the condition."""
        steps = [
            WorkflowStep(
                name="setup",
                bash='echo "should_clean=true"',
            ),
            WorkflowStep(name="fail_step", bash="exit 1"),
            WorkflowStep(
                name="conditional_cleanup",
                bash='echo "cleaned=yes"',
                condition="{{ setup.should_clean }}",
                finally_=True,
            ),
        ]
        workflow = Workflow(name="test", steps=steps)

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            with pytest.raises(WorkflowExecutionError):
                executor.execute()

            # Conditional finally step should have run (condition is true)
            assert "conditional_cleanup" in executor.context
            assert executor.context["conditional_cleanup"]["cleaned"] == "yes"

    def test_finally_step_if_condition_false_skips(self) -> None:
        """Finally steps with false if: condition should be skipped."""
        steps = [
            WorkflowStep(
                name="setup",
                bash='echo "should_clean=false"',
            ),
            WorkflowStep(name="fail_step", bash="exit 1"),
            WorkflowStep(
                name="conditional_cleanup",
                bash='echo "cleaned=yes"',
                condition="{{ setup.should_clean }}",
                finally_=True,
            ),
        ]
        workflow = Workflow(name="test", steps=steps)

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            with pytest.raises(WorkflowExecutionError):
                executor.execute()

            # Condition is false, so the step should be skipped (empty context)
            assert executor.context.get("conditional_cleanup") == {}

    def test_multiple_finally_steps_all_run(self) -> None:
        """All finally steps should run, even if an earlier finally step fails."""
        steps = [
            WorkflowStep(name="fail_step", bash="exit 1"),
            WorkflowStep(
                name="cleanup_a",
                bash='echo "a=yes"',
                finally_=True,
            ),
            WorkflowStep(
                name="cleanup_b",
                bash='echo "b=yes"',
                finally_=True,
            ),
        ]
        workflow = Workflow(name="test", steps=steps)

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow, args={}, artifacts_dir=tmpdir
            )
            with pytest.raises(WorkflowExecutionError):
                executor.execute()

            assert executor.context["cleanup_a"]["a"] == "yes"
            assert executor.context["cleanup_b"]["b"] == "yes"


class TestFinallyStepParsing:
    """Tests for parsing the finally field from YAML-style dicts."""

    def test_parse_finally_true(self) -> None:
        """finally: true should set finally_ on the step."""
        step = _parse_workflow_step(
            {"name": "cleanup", "bash": "echo done", "finally": True}, 0
        )
        assert step.finally_ is True

    def test_parse_finally_false_by_default(self) -> None:
        """Steps without finally should default to False."""
        step = _parse_workflow_step({"name": "work", "bash": "echo work"}, 0)
        assert step.finally_ is False

    def test_finally_on_prompt_part_rejected(self) -> None:
        """prompt_part steps cannot have finally: true."""
        with pytest.raises(WorkflowValidationError, match="prompt_part.*finally"):
            _parse_workflow_step(
                {"name": "pp", "prompt_part": "hello", "finally": True}, 0
            )

    def test_finally_on_nested_step_rejected(self) -> None:
        """Nested (parallel) steps cannot have finally: true."""
        with pytest.raises(WorkflowValidationError, match="Nested.*finally"):
            _parse_workflow_step(
                {"name": "n", "bash": "echo ok", "finally": True},
                0,
                is_nested=True,
            )


class TestFinallyStepValidation:
    """Tests for compile-time validation of finally step ordering."""

    def test_finally_steps_at_end_is_valid(self) -> None:
        """Finally steps at the end of the workflow should pass validation."""
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(name="work", bash="echo work"),
                WorkflowStep(name="cleanup", bash="echo cleanup", finally_=True),
            ],
        )
        errors = _validate_finally_steps(workflow)
        assert errors == []

    def test_non_finally_after_finally_is_invalid(self) -> None:
        """A non-finally step after a finally step should fail validation."""
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(name="cleanup", bash="echo cleanup", finally_=True),
                WorkflowStep(name="work", bash="echo work"),
            ],
        )
        errors = _validate_finally_steps(workflow)
        assert len(errors) == 1
        assert "work" in errors[0]
        assert "finally" in errors[0]

    def test_no_finally_steps_is_valid(self) -> None:
        """Workflow without any finally steps should pass validation."""
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(name="a", bash="echo a"),
                WorkflowStep(name="b", bash="echo b"),
            ],
        )
        errors = _validate_finally_steps(workflow)
        assert errors == []

    def test_multiple_finally_steps_at_end(self) -> None:
        """Multiple finally steps at the end should pass validation."""
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(name="work", bash="echo work"),
                WorkflowStep(name="release", bash="echo release", finally_=True),
                WorkflowStep(name="diff", bash="echo diff", finally_=True),
            ],
        )
        errors = _validate_finally_steps(workflow)
        assert errors == []

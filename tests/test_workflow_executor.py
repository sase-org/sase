"""Tests for the WorkflowExecutor class."""

import tempfile
from unittest.mock import MagicMock

import pytest
from sase.xprompt import HITLHandler, HITLResult, WorkflowExecutor
from sase.xprompt.models import OutputSpec
from sase.xprompt.workflow_executor_utils import parse_bash_output
from sase.xprompt.workflow_models import Workflow, WorkflowExecutionError, WorkflowStep


def _create_test_workflow(
    name: str = "test_workflow",
    steps: list[WorkflowStep] | None = None,
) -> Workflow:
    """Create a test workflow with the given steps."""
    if steps is None:
        steps = [
            WorkflowStep(
                name="step1",
                agent="Test prompt",
                output=OutputSpec(
                    type="json_schema",
                    schema={
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                        "required": ["result"],
                    },
                ),
                hitl=False,
            )
        ]
    return Workflow(
        name=name,
        steps=steps,
    )


def _create_mock_hitl_handler(action: str = "accept") -> HITLHandler:
    """Create a mock HITL handler that returns the specified action."""
    handler = MagicMock(spec=HITLHandler)
    handler.prompt.return_value = HITLResult(action=action)
    return handler


class TestShouldHitl:
    """Tests for the _should_hitl method on WorkflowExecutor."""

    def test_should_hitl_override_false_skips_hitl(self) -> None:
        """Test _should_hitl returns False when override is False."""
        step = WorkflowStep(name="s1", bash="echo ok", hitl=True)
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow,
                args={},
                artifacts_dir=tmpdir,
                hitl_override=False,
            )
            assert executor._should_hitl(step) is False


class TestPythonStepExecution:
    """Tests for Python step execution."""

    def test_python_step_with_jinja_context(self) -> None:
        """Test Python step can access Jinja2 context variables."""
        step = WorkflowStep(
            name="python_step",
            python='print("result={{ input_value }}_processed")',
        )
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow,
                args={"input_value": "hello"},
                artifacts_dir=tmpdir,
            )

            result = executor.execute()

            assert result is True
            assert executor.context["python_step"]["result"] == "hello_processed"

    def test_python_step_validation_error(self) -> None:
        """Test Python step raises error when validation fails."""
        step = WorkflowStep(
            name="python_step",
            python='print("wrong_key=value")',
            output=OutputSpec(
                type="json_schema",
                schema={
                    "type": "object",
                    "properties": {"required_key": {"type": "string"}},
                    "required": ["required_key"],
                },
            ),
        )
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow,
                args={},
                artifacts_dir=tmpdir,
            )

            with pytest.raises(WorkflowExecutionError) as exc_info:
                executor.execute()

            assert "output validation failed" in str(exc_info.value)

    def test_python_step_nonzero_exit_raises_error(self) -> None:
        """Test Python step raises error on non-zero exit code."""
        step = WorkflowStep(
            name="python_step",
            python='import sys; print("error=something failed", file=sys.stderr); sys.exit(1)',
        )
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow,
                args={},
                artifacts_dir=tmpdir,
            )

            with pytest.raises(WorkflowExecutionError) as exc_info:
                executor.execute()

            assert "Python step 'python_step' failed" in str(exc_info.value)

    def test_python_step_with_hitl_accept(self) -> None:
        """Test Python step with HITL that accepts."""
        step = WorkflowStep(
            name="python_step",
            python='print("status=ready")',
            hitl=True,
        )
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_handler = _create_mock_hitl_handler(action="accept")

            executor = WorkflowExecutor(
                workflow=workflow,
                args={},
                artifacts_dir=tmpdir,
                hitl_handler=mock_handler,
            )

            result = executor.execute()

            assert result is True
            assert mock_handler.prompt.called  # type: ignore[attr-defined]
            # Check that HITL was called with "python" step type
            call_args = mock_handler.prompt.call_args  # type: ignore[attr-defined]
            assert call_args[0][1] == "python"
            # Output should have approved flag set
            assert executor.context["python_step"]["approved"] is True
            # Workflow status should be completed, not stuck on waiting_hitl
            assert executor.state.status == "completed"

    def test_python_step_with_hitl_reject(self) -> None:
        """Test Python step with HITL that rejects."""
        step = WorkflowStep(
            name="python_step",
            python='print("status=ready")',
            hitl=True,
        )
        workflow = _create_test_workflow(steps=[step])

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_handler = _create_mock_hitl_handler(action="reject")

            executor = WorkflowExecutor(
                workflow=workflow,
                args={},
                artifacts_dir=tmpdir,
                hitl_handler=mock_handler,
            )

            result = executor.execute()

            assert result is False


class TestParseBashOutput:
    """Tests for parse_bash_output function."""

    def test_parse_json_array(self) -> None:
        """Test parsing JSON array output."""
        output = "[1, 2, 3]"
        result = parse_bash_output(output)
        assert result == [1, 2, 3]

    def test_parse_json_with_leading_control_chars(self) -> None:
        """Test that leading control characters (e.g., bell) don't prevent JSON parsing."""
        output = '\x07\x07\x07{"success": true, "cl_url": "http://example.com"}'
        result = parse_bash_output(output)
        assert result == {"success": True, "cl_url": "http://example.com"}

    def test_parse_key_value(self) -> None:
        """Test parsing key=value output."""
        output = "foo=bar\nbaz=qux"
        result = parse_bash_output(output)
        assert result == {"foo": "bar", "baz": "qux"}

    def test_parse_plain_text_fallback(self) -> None:
        """Test plain text falls back to _output key."""
        output = "just some text"
        result = parse_bash_output(output)
        assert result == {"_output": "just some text"}


class TestEmbeddedWorkflowExpansion:
    """Tests for embedded workflow expansion in prompts."""

    def test_embedded_workflow_hashes_inline_gets_newlines(self) -> None:
        """Test that ### content gets \\n\\n prepended when not at line start."""
        from unittest.mock import patch

        workflow_with_hashes = Workflow(
            name="inject_workflow",
            steps=[
                WorkflowStep(
                    name="inject",
                    prompt_part="### Section Header\nSection content",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            main_workflow = _create_test_workflow()
            executor = WorkflowExecutor(
                workflow=main_workflow,
                args={},
                artifacts_dir=tmpdir,
            )

            with patch("sase.xprompt.loader.get_all_workflows") as mock_get_workflows:
                mock_get_workflows.return_value = {
                    "inject_workflow": workflow_with_hashes
                }

                # Test case: workflow ref inline (not at line start)
                prompt = "Context text. #inject_workflow"
                expanded, _, _ = executor._expand_embedded_workflows_in_prompt(prompt)

                # Should prepend \n\n before the ### content
                assert "\n\n### Section Header" in expanded


class TestOutputTypesPreservation:
    """Tests for output_types preservation in _save_prompt_step_marker."""


class TestSubstepSuffix:
    """Tests for the get_substep_suffix helper function."""

    def test_substep_suffix_double_letters(self) -> None:
        """Test that indices 26+ map to aa, ab, etc."""
        from sase.xprompt.workflow_output import get_substep_suffix

        assert get_substep_suffix(26) == "aa"
        assert get_substep_suffix(27) == "ab"
        assert get_substep_suffix(51) == "az"
        assert get_substep_suffix(52) == "ba"


class TestParentStepContext:
    """Tests for parent step context in embedded workflow output."""

    def test_on_step_start_without_parent_context(self) -> None:
        """Test that on_step_start uses regular numbering without parent context."""
        from io import StringIO

        from rich.console import Console
        from sase.xprompt.workflow_output import WorkflowOutputHandler

        output = StringIO()
        console = Console(file=output, force_terminal=False, no_color=True, width=100)
        handler = WorkflowOutputHandler(console=console)

        # Call on_step_start without parent context
        handler.on_step_start(
            step_name="test_step",
            step_type="agent",
            step_index=2,
            total_steps=5,
        )

        # Check output contains the expected format "3/5" (0-indexed + 1)
        result = output.getvalue()
        assert "Step 3/5: test_step (agent)" in result

    def test_on_step_start_multiple_substeps(self) -> None:
        """Test formatting of multiple embedded substeps."""
        from io import StringIO

        from rich.console import Console
        from sase.xprompt.workflow_output import (
            ParentStepContext,
            WorkflowOutputHandler,
        )

        output = StringIO()
        console = Console(file=output, force_terminal=False, no_color=True, width=100)
        handler = WorkflowOutputHandler(console=console)

        parent_ctx = ParentStepContext(step_index=2, total_steps=10)

        # Substeps 0, 1, 2 should produce 3a, 3b, 3c
        for i in range(3):
            handler.on_step_start(
                step_name=f"substep_{i}",
                step_type="bash",
                step_index=i,
                total_steps=3,
                parent_step_context=parent_ctx,
            )

        result = output.getvalue()
        assert "Step 3a/10:" in result
        assert "Step 3b/10:" in result
        assert "Step 3c/10:" in result

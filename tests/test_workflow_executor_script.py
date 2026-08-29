"""Tests for WorkflowExecutor Python and bash script steps."""

import json
import os
import tempfile
from pathlib import Path

import pytest
from sase.xprompt import WorkflowExecutor
from sase.xprompt.models import OutputSpec
from sase.xprompt.workflow_models import Workflow, WorkflowExecutionError, WorkflowStep

from tests._workflow_executor_helpers import (
    _create_mock_hitl_handler,
    _create_test_workflow,
)


class TestPythonStepExecution:
    """Tests for Python step execution."""

    def test_workflow_hidden_is_persisted_to_state(self) -> None:
        """Workflow-level hidden is independent from step-level hidden."""
        step = WorkflowStep(name="python_step", python='print("ok=true")')
        workflow = Workflow(name="hidden_parent", steps=[step], hidden=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            executor = WorkflowExecutor(
                workflow=workflow,
                args={},
                artifacts_dir=tmpdir,
            )

            assert executor.execute() is True

            state_path = Path(tmpdir) / "workflow_state.json"
            data = json.loads(state_path.read_text(encoding="utf-8"))

        assert data["hidden"] is True
        assert data["steps"][0]["hidden"] is False

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


class TestScriptStepChdir:
    """Tests for script-step _chdir handling."""

    def test_bash_chdir_sets_active_project_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """WorkflowExecutor records the assigned project dir when changing cwd."""
        original_dir = os.getcwd()
        target_dir = tmp_path / "project"
        target_dir.mkdir()
        monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
        step = WorkflowStep(
            name="change_dir",
            bash=f"echo '_chdir={target_dir}'",
        )
        workflow = _create_test_workflow(steps=[step])

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                executor = WorkflowExecutor(
                    workflow=workflow,
                    args={},
                    artifacts_dir=tmpdir,
                )

                assert executor.execute() is True

            assert os.getcwd() == str(target_dir)
            assert os.environ["SASE_ACTIVE_PROJECT_DIR"] == str(target_dir)
            assert "_chdir" not in executor.context["change_dir"]
        finally:
            os.chdir(original_dir)

    def test_chdir_runner_bound_workspace_updates_env_and_callback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Runner-bound workspace outputs update env and notify the runner."""
        original_dir = os.getcwd()
        target_dir = tmp_path / "project_21"
        target_dir.mkdir()
        monkeypatch.delenv("SASE_ACTIVE_PROJECT_DIR", raising=False)
        monkeypatch.delenv("SASE_AGENT_WORKSPACE_NUM", raising=False)
        events: list[tuple[dict[str, object], str]] = []
        step = WorkflowStep(
            name="change_dir",
            bash=(
                f"echo '_chdir={target_dir}'\n"
                "echo 'workspace_num=21'\n"
                "echo 'runner_bound_workspace=true'"
            ),
            output=OutputSpec(
                type="json_schema",
                schema={
                    "properties": {
                        "workspace_num": {"type": "int"},
                        "runner_bound_workspace": {"type": "bool"},
                    },
                },
            ),
        )
        workflow = _create_test_workflow(steps=[step])

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                executor = WorkflowExecutor(
                    workflow=workflow,
                    args={},
                    artifacts_dir=tmpdir,
                    workspace_rebind_callback=(
                        lambda output, path: events.append((dict(output), path))
                    ),
                )

                assert executor.execute() is True

            assert os.environ["SASE_ACTIVE_PROJECT_DIR"] == str(target_dir)
            assert os.environ["SASE_AGENT_WORKSPACE_NUM"] == "21"
            assert events == [
                (
                    {"workspace_num": 21, "runner_bound_workspace": True},
                    str(target_dir),
                )
            ]
        finally:
            os.chdir(original_dir)

"""Tests for embedded workflow environment variable injection."""

import os
from typing import Any
from unittest.mock import patch

import pytest

from sase.xprompt.workflow_executor_steps_embedded import EmbeddedWorkflowMixin
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowState,
    WorkflowStep,
)

_LOADER_PATH = "sase.xprompt.loader.get_all_workflows"


def _make_workflow_with_env(
    name: str,
    environment: dict[str, str],
    prompt_part: str = "expanded content",
) -> Workflow:
    """Create a workflow with an environment block and a prompt_part step."""
    return Workflow(
        name=name,
        steps=[WorkflowStep(name="inject", prompt_part=prompt_part)],
        environment=environment,
    )


# ---------------------------------------------------------------------------
# _FakeExecutor for testing _expand_embedded_workflows_in_prompt
# ---------------------------------------------------------------------------


class _FakeExecutor(EmbeddedWorkflowMixin):
    """Minimal fake providing attributes required by the mixin."""

    def __init__(self) -> None:
        self.workflow = Workflow(
            name="parent",
            steps=[WorkflowStep(name="main", agent="test prompt")],
        )
        self.context: dict[str, Any] = {}
        self.artifacts_dir = "/nonexistent"
        self.hitl_handler = None
        self.output_handler = None
        self.state = WorkflowState(
            workflow_name="parent",
            status="running",
            current_step_index=0,
            steps=[],
            context={},
            artifacts_dir="/nonexistent",
            start_time="",
        )
        self._current_embedded_workflow_name: str | None = None

    def _get_step_type(self, step: WorkflowStep) -> str:
        if step.is_bash_step():
            return "bash"
        if step.is_python_step():
            return "python"
        return "agent"

    def _evaluate_condition(self, condition: str) -> bool:
        return True

    def _save_prompt_step_marker(self, *args: Any, **kwargs: Any) -> None:
        pass

    def _execute_prompt_step(self, step: WorkflowStep, step_state: Any) -> bool:
        return True

    def _execute_python_step(self, step: WorkflowStep, step_state: Any) -> bool:
        return True

    def _execute_bash_step(self, step: WorkflowStep, step_state: Any) -> bool:
        step_state.output = {}
        self.context[step.name] = {}
        return True


# ============================================================================
# Tests for _expand_embedded_workflows_in_prompt (WorkflowExecutor path)
# ============================================================================


class TestExpandEmbeddedInjectsEnv:
    """Environment injection via _expand_embedded_workflows_in_prompt."""

    def test_embedded_workflow_injects_environment(self) -> None:
        """Embedded workflow with environment: {FOO: bar} sets os.environ."""
        wf = _make_workflow_with_env("test_wf", {"FOO": "bar"})
        executor = _FakeExecutor()

        os.environ.pop("FOO", None)

        with patch(_LOADER_PATH, return_value={"test_wf": wf}):
            executor._expand_embedded_workflows_in_prompt("#test_wf do stuff")

        assert os.environ.get("FOO") == "bar"
        os.environ.pop("FOO", None)

    def test_environment_template_rendering(self) -> None:
        """Environment values are rendered as Jinja2 templates with args."""
        from sase.xprompt.models import InputArg

        wf = _make_workflow_with_env("mywf", {"MY_VAR": "{{ method }}"})
        wf.inputs = [InputArg(name="method")]
        executor = _FakeExecutor()

        os.environ.pop("MY_VAR", None)

        with patch(_LOADER_PATH, return_value={"mywf": wf}):
            executor._expand_embedded_workflows_in_prompt("#mywf(some_value) do stuff")

        assert os.environ.get("MY_VAR") == "some_value"
        os.environ.pop("MY_VAR", None)

    def test_multiple_env_vars_injected(self) -> None:
        """Multiple environment variables are all injected."""
        wf = _make_workflow_with_env("mywf", {"VAR_A": "alpha", "VAR_B": "beta"})
        executor = _FakeExecutor()

        os.environ.pop("VAR_A", None)
        os.environ.pop("VAR_B", None)

        with patch(_LOADER_PATH, return_value={"mywf": wf}):
            executor._expand_embedded_workflows_in_prompt("#mywf do stuff")

        assert os.environ.get("VAR_A") == "alpha"
        assert os.environ.get("VAR_B") == "beta"
        os.environ.pop("VAR_A", None)
        os.environ.pop("VAR_B", None)


# ============================================================================
# Tests for expand_embedded_workflows_in_query (standalone path)
# ============================================================================


class TestQueryExpandInjectsEnv:
    """Environment injection via expand_embedded_workflows_in_query."""

    def test_embedded_workflow_injects_environment(self) -> None:
        """Embedded workflow with environment: {FOO: bar} sets os.environ."""
        from sase.main.query_handler._embedded_workflows import (
            expand_embedded_workflows_in_query,
        )

        wf = _make_workflow_with_env("test_wf", {"FOO": "bar"})

        os.environ.pop("FOO", None)

        with patch(_LOADER_PATH, return_value={"test_wf": wf}):
            expand_embedded_workflows_in_query("#test_wf do stuff")

        assert os.environ.get("FOO") == "bar"
        os.environ.pop("FOO", None)

    def test_environment_template_rendering(self) -> None:
        """Environment values are rendered as Jinja2 templates with args."""
        from sase.main.query_handler._embedded_workflows import (
            expand_embedded_workflows_in_query,
        )
        from sase.xprompt.models import InputArg

        wf = _make_workflow_with_env("mywf", {"MY_VAR": "{{ method }}"})
        wf.inputs = [InputArg(name="method")]

        os.environ.pop("MY_VAR", None)

        with patch(_LOADER_PATH, return_value={"mywf": wf}):
            expand_embedded_workflows_in_query("#mywf(some_value) do stuff")

        assert os.environ.get("MY_VAR") == "some_value"
        os.environ.pop("MY_VAR", None)

    def test_multiple_env_vars_injected(self) -> None:
        """Multiple environment variables are all injected."""
        from sase.main.query_handler._embedded_workflows import (
            expand_embedded_workflows_in_query,
        )

        wf = _make_workflow_with_env("mywf", {"VAR_A": "alpha", "VAR_B": "beta"})

        os.environ.pop("VAR_A", None)
        os.environ.pop("VAR_B", None)

        with patch(_LOADER_PATH, return_value={"mywf": wf}):
            expand_embedded_workflows_in_query("#mywf do stuff")

        assert os.environ.get("VAR_A") == "alpha"
        assert os.environ.get("VAR_B") == "beta"
        os.environ.pop("VAR_A", None)
        os.environ.pop("VAR_B", None)

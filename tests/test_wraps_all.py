"""Tests for the wraps_all workflow field."""

from typing import Any
from unittest.mock import patch

import pytest

from sase.xprompt.workflow_executor_steps_embedded import (
    EmbeddedWorkflowMixin,
    _PendingEmbeddedWorkflow,
)
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowExecutionError,
    WorkflowStep,
    WorkflowState,
)


# ============================================================================
# Loader tests: wraps_all parsed from YAML
# ============================================================================


# ============================================================================
# Validation: multiple wraps_all raises WorkflowExecutionError
# ============================================================================


def _make_workflow(
    name: str, *, wraps_all: bool = False, has_prompt_part: bool = True
) -> Workflow:
    """Create a minimal embeddable workflow for testing."""
    steps = []
    if has_prompt_part:
        steps.append(WorkflowStep(name="setup", bash="echo setup"))
        steps.append(WorkflowStep(name="inject", prompt_part=""))
        steps.append(WorkflowStep(name="teardown", bash="echo teardown"))
    else:
        steps.append(WorkflowStep(name="run", agent="Do thing"))
    return Workflow(name=name, steps=steps, wraps_all=wraps_all)


class _FakeExecutor(EmbeddedWorkflowMixin):
    """Minimal fake providing attributes required by the mixin."""

    def __init__(self, workflows: dict[str, Workflow]) -> None:
        self._workflows = workflows
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


def test_multiple_wraps_all_raises_error() -> None:
    """Multiple wraps_all workflows in one prompt raises WorkflowExecutionError."""
    wf_git = _make_workflow("git", wraps_all=True)
    wf_hg = _make_workflow("hg", wraps_all=True)

    executor = _FakeExecutor({"git": wf_git, "hg": wf_hg})

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"git": wf_git, "hg": wf_hg},
    ):
        with pytest.raises(WorkflowExecutionError, match="Multiple wraps_all"):
            executor._expand_embedded_workflows_in_prompt(
                "#git:main #hg:cl123 Do something"
            )


def test_single_wraps_all_does_not_raise() -> None:
    """A single wraps_all workflow with other non-wraps_all workflows is fine."""
    wf_git = _make_workflow("git", wraps_all=True)
    wf_commit = _make_workflow("commit", wraps_all=False)

    executor = _FakeExecutor({"git": wf_git, "commit": wf_commit})

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"git": wf_git, "commit": wf_commit},
    ):
        # Should not raise
        prompt, embedded, _ = executor._expand_embedded_workflows_in_prompt(
            "#git:main #commit:fix Do something"
        )
        # Should return results without error
        assert isinstance(prompt, str)


# ============================================================================
# Ordering: wraps_all pre-steps first, post-steps last
# ============================================================================


class _TrackingExecutor(_FakeExecutor):
    """Executor that tracks the order of pre-step execution."""

    def __init__(self, workflows: dict[str, Workflow]) -> None:
        super().__init__(workflows)
        self.pre_step_order: list[str] = []

    def _execute_embedded_workflow_steps(
        self,
        steps: list[WorkflowStep],
        embedded_context: dict[str, Any],
        parent_step_name: str,
        **kwargs: Any,
    ) -> bool:
        # Track which workflow's pre-steps are being executed
        # parent_step_name is "embedded:<name>"
        wf_name = (
            parent_step_name.split(":", 1)[1]
            if ":" in parent_step_name
            else parent_step_name
        )
        self.pre_step_order.append(wf_name)
        return True


# ============================================================================
# Regression: without wraps_all, right-to-left order preserved
# ============================================================================


# ============================================================================
# Fenced code block protection
# ============================================================================


# ============================================================================
# _PendingEmbeddedWorkflow dataclass tests
# ============================================================================


def test_pending_embedded_workflow_defaults() -> None:
    """_PendingEmbeddedWorkflow has correct defaults."""
    wf = _make_workflow("test")
    p = _PendingEmbeddedWorkflow(
        name="test",
        workflow=wf,
        match_start=0,
        match_end=5,
        args={"key": "val"},
        explicit_args={"key": "val"},
    )
    assert p.embedded_context == {}
    assert p.rendered_prompt_part == ""
    assert p.name == "test"

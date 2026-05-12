"""Regression tests for the project-local fix_just workflow."""

from pathlib import Path

import pytest
from sase.xprompt.workflow_executor import WorkflowExecutor
from sase.xprompt.workflow_loader import _load_workflow_from_file
from sase.xprompt.workflow_models import StepState, StepStatus, WorkflowStep


def test_fix_just_decide_fixers_renders_bool_step_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real fix_just workflow renders typed bools into valid Python."""
    workflow_path = Path(__file__).resolve().parents[1] / "xprompts" / "fix_just.yml"
    workflow = _load_workflow_from_file(workflow_path)
    assert workflow is not None

    executed_bash_steps: list[str] = []
    launched_agents: list[str] = []

    def fake_execute_bash_step(
        self: WorkflowExecutor,
        step: WorkflowStep,
        step_state: StepState,
    ) -> bool:
        executed_bash_steps.append(step.name)
        step_state.output = {}
        self.context[step.name] = {}
        self.state.context = dict(self.context)
        return True

    def fake_execute_prompt_step(
        self: WorkflowExecutor,
        step: WorkflowStep,
        step_state: StepState,
    ) -> bool:
        launched_agents.append(step.name)
        step_state.output = {}
        self.context[step.name] = {}
        self.state.context = dict(self.context)
        return True

    monkeypatch.setattr(
        WorkflowExecutor,
        "_execute_bash_step",
        fake_execute_bash_step,
    )
    monkeypatch.setattr(
        WorkflowExecutor,
        "_execute_prompt_step",
        fake_execute_prompt_step,
    )

    executor = WorkflowExecutor(
        workflow=workflow,
        args={
            "_just_fmt_check": {"success": True},
            "_just_lint": {"success": False},
            "_just_test": {"success": True},
        },
        artifacts_dir=str(tmp_path),
    )

    assert executor.execute() is True

    decide_output = executor.context["decide_fixers"]
    assert decide_output["fmt_success"] is True
    assert decide_output["lint_success"] is False
    assert decide_output["test_success"] is True
    assert decide_output["launch_fmt"] is False
    assert decide_output["launch_linters"] is True
    assert decide_output["launch_tests"] is False
    assert executed_bash_steps == ["_just_install"]
    assert launched_agents == ["fix_linters"]

    step_statuses = {step.name: step.status for step in executor.state.steps}
    assert step_statuses["_just_install"] is StepStatus.COMPLETED
    assert step_statuses["_just_fmt_check"] is StepStatus.SKIPPED
    assert step_statuses["_just_lint"] is StepStatus.SKIPPED
    assert step_statuses["_just_test"] is StepStatus.SKIPPED
    assert step_statuses["decide_fixers"] is StepStatus.COMPLETED
    assert step_statuses["fix_fmt"] is StepStatus.SKIPPED
    assert step_statuses["fix_linters"] is StepStatus.COMPLETED
    assert step_statuses["fix_tests"] is StepStatus.SKIPPED

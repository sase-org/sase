"""Regression tests for the project-local fix_just workflow."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from sase.llm_provider.messages import AIMessage
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.tags import XPromptTag
from sase.xprompt.workflow_executor import WorkflowExecutor
from sase.xprompt.workflow_loader import _load_workflow_from_file
from sase.xprompt.workflow_models import StepState, StepStatus, Workflow, WorkflowStep


_PR_ENV_KEYS = ("SASE_COMMIT_METHOD", "SASE_PR_NAME", "SASE_PR_STATUS")


def _load_fix_just_workflow() -> Workflow:
    workflow_path = (
        Path(__file__).resolve().parents[1] / "sase" / "xprompts" / "fix_just.yml"
    )
    workflow = _load_workflow_from_file(workflow_path)
    assert workflow is not None
    return workflow


def test_fix_just_test_step_confirms_failures_before_reporting_failure() -> None:
    """The real fix_just workflow retries just test before reporting failure."""
    workflow = _load_fix_just_workflow()

    test_step = next(step for step in workflow.steps if step.name == "_just_test")

    assert test_step.is_bash_step()
    assert test_step.bash is not None
    assert test_step.bash.count("just test") == 2
    assert test_step.output is not None
    assert test_step.output.schema["properties"] == {"success": {"type": "bool"}}


def test_fix_just_lint_step_confirms_failures_before_reporting_failure() -> None:
    """The real fix_just workflow retries just lint before reporting failure."""
    workflow = _load_fix_just_workflow()

    lint_step = next(step for step in workflow.steps if step.name == "_just_lint")

    assert lint_step.is_bash_step()
    assert lint_step.bash is not None
    assert lint_step.bash.count("just lint") == 2
    assert lint_step.output is not None
    assert lint_step.output.schema["properties"] == {"success": {"type": "bool"}}


def test_fix_just_deflaked_test_success_does_not_launch_test_fixer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the final _just_test result is green, the test repair agent is skipped."""
    workflow = _load_fix_just_workflow()

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
            "_just_lint": {"success": True},
            "_just_test": {"success": True},
        },
        artifacts_dir=str(tmp_path),
    )

    assert executor.execute() is True

    decide_output = executor.context["decide_fixers"]
    assert decide_output["fmt_success"] is True
    assert decide_output["lint_success"] is True
    assert decide_output["test_success"] is True
    assert decide_output["launch_fmt"] is False
    assert decide_output["launch_linters"] is False
    assert decide_output["launch_tests"] is False
    assert executed_bash_steps == ["_just_install"]
    assert launched_agents == []

    step_statuses = {step.name: step.status for step in executor.state.steps}
    assert step_statuses["fix_fmt"] is StepStatus.SKIPPED
    assert step_statuses["fix_linters"] is StepStatus.SKIPPED
    assert step_statuses["fix_tests"] is StepStatus.SKIPPED


def test_fix_just_decide_fixers_renders_bool_step_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real fix_just workflow renders typed bools into valid Python."""
    workflow = _load_fix_just_workflow()

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
            "_just_test": {"success": False},
        },
        artifacts_dir=str(tmp_path),
    )

    assert executor.execute() is True

    decide_output = executor.context["decide_fixers"]
    assert decide_output["fmt_success"] is True
    assert decide_output["lint_success"] is False
    assert decide_output["test_success"] is False
    assert decide_output["launch_fmt"] is False
    assert decide_output["launch_linters"] is True
    assert decide_output["launch_tests"] is True
    assert executed_bash_steps == ["_just_install"]
    assert launched_agents == ["fix_linters", "fix_tests"]

    step_statuses = {step.name: step.status for step in executor.state.steps}
    assert step_statuses["_just_install"] is StepStatus.COMPLETED
    assert step_statuses["_just_fmt_check"] is StepStatus.SKIPPED
    assert step_statuses["_just_lint"] is StepStatus.SKIPPED
    assert step_statuses["_just_test"] is StepStatus.SKIPPED
    assert step_statuses["decide_fixers"] is StepStatus.COMPLETED
    assert step_statuses["fix_fmt"] is StepStatus.SKIPPED
    assert step_statuses["fix_linters"] is StepStatus.COMPLETED
    assert step_statuses["fix_tests"] is StepStatus.COMPLETED


def test_fix_just_agent_steps_expand_pr_xprompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real fix_just agent steps embed #pr before invoking agents."""
    workflow = _load_fix_just_workflow()

    pr_path = (
        Path(__file__).resolve().parents[1] / "src" / "sase" / "xprompts" / "pr.yml"
    )
    pr_workflow = _load_workflow_from_file(pr_path)
    assert pr_workflow is not None

    gh_workflow = Workflow(
        name="gh",
        inputs=[InputArg(name="gh_ref", type=InputType.WORD)],
        steps=[WorkflowStep(name="inject", prompt_part="")],
        source_path="plugin:sase_github/gh.yml",
        tags=frozenset({XPromptTag.vcs}),
    )
    workflow_catalog = {"gh": gh_workflow, "pr": pr_workflow}

    captured_prompts: dict[str, str] = {}
    captured_env: dict[str, dict[str, str | None]] = {}
    original_execute_bash_step = WorkflowExecutor._execute_bash_step
    original_execute_python_step = WorkflowExecutor._execute_python_step

    def fake_execute_bash_step(
        self: WorkflowExecutor,
        step: WorkflowStep,
        step_state: StepState,
    ) -> bool:
        if step.name == "_just_install":
            step_state.output = {}
            self.context[step.name] = {}
            self.state.context = dict(self.context)
            return True
        return original_execute_bash_step(self, step, step_state)

    def fake_execute_python_step(
        self: WorkflowExecutor,
        step: WorkflowStep,
        step_state: StepState,
    ) -> bool:
        if step.name == "check_changes":
            step_state.output = {"has_changes": False}
            self.context[step.name] = step_state.output
            self.state.context = dict(self.context)
            return True
        if step.name == "_has_commit_result":
            step_state.output = {"exists": False}
            self.context[step.name] = step_state.output
            self.state.context = dict(self.context)
            return True
        return original_execute_python_step(self, step, step_state)

    def fake_invoke_agent(prompt: str, **kwargs: object) -> AIMessage:
        agent_type = str(kwargs["agent_type"])
        step_name = agent_type.rsplit("-", 1)[-1]
        captured_prompts[step_name] = prompt
        captured_env[step_name] = {key: os.environ.get(key) for key in _PR_ENV_KEYS}
        return AIMessage(content="ok")

    for key in _PR_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    with (
        patch.object(WorkflowExecutor, "_execute_bash_step", fake_execute_bash_step),
        patch.object(
            WorkflowExecutor,
            "_execute_python_step",
            fake_execute_python_step,
        ),
        patch("sase.xprompt.processor.get_all_xprompts", return_value={}),
        patch("sase.xprompt.loader.get_all_workflows", return_value=workflow_catalog),
        patch("sase.xprompt.loader.get_all_prompts", return_value=workflow_catalog),
        patch("sase.llm_provider.invoke_agent", side_effect=fake_invoke_agent),
    ):
        executor = WorkflowExecutor(
            workflow=workflow,
            args={
                "_just_fmt_check": {"success": True},
                "_just_lint": {"success": False},
                "_just_test": {"success": False},
            },
            artifacts_dir=str(tmp_path),
        )

        assert executor.execute() is True

    assert set(captured_prompts) == {"fix_linters", "fix_tests"}
    # Prompts are prose-wrapped at the agent prompt width, so collapse runs of
    # whitespace before matching phrases that may straddle a wrap boundary.
    normalized = {
        name: " ".join(prompt.split()) for name, prompt in captured_prompts.items()
    }
    for prompt in normalized.values():
        assert "#pr(" not in prompt
        assert "should make the necessary file changes" in prompt
        assert "post-completion finalizer instructs you to commit" in prompt

    assert "`just lint` command" in normalized["fix_linters"]
    assert "`just test` command" in normalized["fix_tests"]

    assert captured_env["fix_linters"] == {
        "SASE_COMMIT_METHOD": "create_pull_request",
        "SASE_PR_NAME": "fix_just_linters",
        "SASE_PR_STATUS": "draft",
    }
    assert captured_env["fix_tests"] == {
        "SASE_COMMIT_METHOD": "create_pull_request",
        "SASE_PR_NAME": "fix_just_tests",
        "SASE_PR_STATUS": "draft",
    }

    for step_name, pr_name in (
        ("fix_linters", "fix_just_linters"),
        ("fix_tests", "fix_just_tests"),
    ):
        metadata_path = tmp_path / f"embedded_workflows_{step_name}.json"
        metadata = json.loads(metadata_path.read_text())
        assert {
            "name": "pr",
            "args": {"name": pr_name},
            "tags": ["rollover"],
        } in metadata

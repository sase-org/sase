"""Integration tests for runner provider execution pipeline (Phase 2)."""

import warnings
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from sase.runner_provider import PostAgentResult, RunnerContext, RunnerProvider
from sase.xprompt.workflow_executor_steps_embedded import EmbeddedWorkflowMixin
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowExecutionError,
    WorkflowState,
    WorkflowStep,
)


# ============================================================================
# Helpers
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


class _MockProvider(RunnerProvider):
    """Mock runner provider for testing."""

    @property
    def name(self) -> str:
        return "git"

    def pre_agent(
        self, ref: str, *, n: int | None = None, release: bool = True
    ) -> RunnerContext:
        return RunnerContext(checkout_target=ref, should_release=release)

    def post_agent(self, ctx: RunnerContext) -> PostAgentResult:
        return PostAgentResult()


# ============================================================================
# Backward compat tests: _expand_embedded_workflows_in_prompt
# ============================================================================


class TestWrapsAllRunnerProviderBackwardCompat:
    """Tests for wraps_all backward compat with runner directives."""

    def test_wraps_all_skipped_when_runner_directive_active(self) -> None:
        """wraps_all workflow removed when matching runner directive is active."""
        wf_git = _make_workflow("git", wraps_all=True)
        executor = _FakeExecutor({"git": wf_git})

        with (
            patch(
                "sase.xprompt.loader.get_all_workflows",
                return_value={"git": wf_git},
            ),
            patch(
                "sase.runner_provider.get_runner_provider_names",
                return_value=frozenset({"git"}),
            ),
        ):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                prompt, embedded, _ = executor._expand_embedded_workflows_in_prompt(
                    "#git:main Do something",
                    runner_active_provider_name="git",
                )

        # The wraps_all workflow should have been skipped entirely
        assert embedded == []
        # A DeprecationWarning should have been emitted
        deprecation_warnings = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) == 1
        assert "redundant" in str(deprecation_warnings[0].message)

    def test_wraps_all_deprecation_when_no_runner_directive(self) -> None:
        """wraps_all workflow still executes but emits deprecation without runner."""
        wf_git = _make_workflow("git", wraps_all=True)
        executor = _FakeExecutor({"git": wf_git})

        with (
            patch(
                "sase.xprompt.loader.get_all_workflows",
                return_value={"git": wf_git},
            ),
            patch(
                "sase.runner_provider.get_runner_provider_names",
                return_value=frozenset({"git"}),
            ),
        ):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                prompt, embedded, _ = executor._expand_embedded_workflows_in_prompt(
                    "#git:main Do something",
                    runner_active_provider_name=None,
                )

        # The workflow should still execute (not skipped)
        assert len(embedded) == 1
        assert embedded[0].workflow_name == "git"
        # A DeprecationWarning should have been emitted
        deprecation_warnings = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) == 1
        assert "migrated" in str(deprecation_warnings[0].message)

    def test_wraps_all_non_runner_provider_unaffected(self) -> None:
        """wraps_all workflow not matching a runner provider has no warnings."""
        wf_custom = _make_workflow("custom", wraps_all=True)
        executor = _FakeExecutor({"custom": wf_custom})

        with (
            patch(
                "sase.xprompt.loader.get_all_workflows",
                return_value={"custom": wf_custom},
            ),
            patch(
                "sase.runner_provider.get_runner_provider_names",
                return_value=frozenset({"git"}),
            ),
        ):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                prompt, embedded, _ = executor._expand_embedded_workflows_in_prompt(
                    "#custom:main Do something",
                    runner_active_provider_name=None,
                )

        # The workflow should still execute normally
        assert len(embedded) == 1
        assert embedded[0].workflow_name == "custom"
        # No DeprecationWarnings
        deprecation_warnings = [
            x for x in w if issubclass(x.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) == 0


# ============================================================================
# Prompt step lifecycle tests
# ============================================================================


def _make_mock_early_result(
    runner: tuple[str, str, dict[str, str]] | None = None,
):
    """Build a mock PreprocessResult with optional runner directive."""
    from sase.xprompt.directives import PromptDirectives

    mock_result = MagicMock()
    mock_result.prompt = "test prompt"
    mock_result.directives = PromptDirectives(runner=runner)
    return mock_result


def _make_prompt_step_executor():
    """Build a minimal executor with PromptStepMixin for testing."""
    from sase.xprompt.workflow_executor_steps_prompt import PromptStepMixin

    class _FakePromptExecutor(PromptStepMixin):
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

        def _save_state(self) -> None:
            pass

        def _save_prompt_step_marker(self, *args: Any, **kwargs: Any) -> None:
            pass

        def _expand_embedded_workflows_in_prompt(
            self, prompt: str, **kwargs: Any
        ) -> tuple[str, list, int]:
            return prompt, [], 0

        def _execute_embedded_workflow_steps(self, *args: Any, **kwargs: Any) -> bool:
            return True

        def _propagate_last_embedded_output(self, *args: Any, **kwargs: Any) -> None:
            pass

        def _should_hitl(self, step: WorkflowStep) -> bool:
            return False

    return _FakePromptExecutor()


class TestRunnerProviderLifecycle:
    """Tests for runner provider pre/post lifecycle in _execute_prompt_step."""

    @patch("sase.xprompt.workflow_executor_steps_prompt.get_runner_providers")
    def test_pre_agent_called_before_agent_post_agent_after(
        self, mock_get_providers: MagicMock
    ) -> None:
        """Verify call ordering: pre_agent → invoke_agent → post_agent."""
        provider = MagicMock(spec=RunnerProvider)
        provider.name = "git"
        provider.pre_agent.return_value = RunnerContext(checkout_target="main")
        provider.post_agent.return_value = PostAgentResult()
        mock_get_providers.return_value = {"git": provider}

        executor = _make_prompt_step_executor()
        step = WorkflowStep(name="main", agent="Do work")

        call_order: list[str] = []
        provider.pre_agent.side_effect = lambda *a, **kw: (
            call_order.append("pre_agent"),
            RunnerContext(),
        )[1]
        provider.post_agent.side_effect = lambda *a, **kw: (
            call_order.append("post_agent"),
            PostAgentResult(),
        )[1]

        early = _make_mock_early_result(runner=("git", "main", {}))
        mock_response = MagicMock()
        mock_response.content = "response text"

        from sase.xprompt.workflow_models import StepState

        step_state = StepState(name="main")

        with (
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_early",
                return_value=early,
            ),
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_late",
                return_value="processed prompt",
            ),
            patch(
                "sase.llm_provider.invoke_agent",
                side_effect=lambda *a, **kw: (
                    call_order.append("invoke_agent"),
                    mock_response,
                )[1],
            ),
            patch(
                "sase.shared_utils.ensure_str_content",
                return_value="response text",
            ),
            patch(
                "sase.xprompt.extract_structured_content",
                return_value=({}, None),
            ),
            patch(
                "sase.xprompt.workflow_executor_steps_prompt.capture_vcs_diff",
                return_value=None,
            ),
        ):
            result = executor._execute_prompt_step(step, step_state)

        assert result is True
        assert call_order == ["pre_agent", "invoke_agent", "post_agent"]

    @patch("sase.xprompt.workflow_executor_steps_prompt.get_runner_providers")
    def test_post_agent_runs_on_agent_failure(
        self, mock_get_providers: MagicMock
    ) -> None:
        """post_agent still called when invoke_agent raises."""
        provider = MagicMock(spec=RunnerProvider)
        provider.name = "git"
        provider.pre_agent.return_value = RunnerContext(checkout_target="main")
        provider.post_agent.return_value = PostAgentResult()
        mock_get_providers.return_value = {"git": provider}

        executor = _make_prompt_step_executor()
        step = WorkflowStep(name="main", agent="Do work")

        early = _make_mock_early_result(runner=("git", "main", {}))

        from sase.xprompt.workflow_models import StepState

        step_state = StepState(name="main")

        with (
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_early",
                return_value=early,
            ),
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_late",
                return_value="processed prompt",
            ),
            patch(
                "sase.llm_provider.invoke_agent",
                side_effect=RuntimeError("agent crashed"),
            ),
            patch(
                "sase.shared_utils.ensure_str_content",
                return_value="response text",
            ),
            patch(
                "sase.xprompt.workflow_executor_steps_prompt.capture_vcs_diff",
                return_value=None,
            ),
        ):
            with pytest.raises(RuntimeError, match="agent crashed"):
                executor._execute_prompt_step(step, step_state)

        # post_agent must still have been called (finally block)
        provider.post_agent.assert_called_once()

    @patch("sase.xprompt.workflow_executor_steps_prompt.get_runner_providers")
    def test_runner_diff_path_propagated(self, mock_get_providers: MagicMock) -> None:
        """PostAgentResult(diff_path=...) → step_state.output["diff_path"]."""
        provider = MagicMock(spec=RunnerProvider)
        provider.name = "git"
        provider.pre_agent.return_value = RunnerContext(checkout_target="main")
        provider.post_agent.return_value = PostAgentResult(diff_path="/tmp/runner.diff")
        mock_get_providers.return_value = {"git": provider}

        executor = _make_prompt_step_executor()
        step = WorkflowStep(name="main", agent="Do work")

        early = _make_mock_early_result(runner=("git", "main", {}))
        mock_response = MagicMock()
        mock_response.content = "response text"

        from sase.xprompt.workflow_models import StepState

        step_state = StepState(name="main")

        with (
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_early",
                return_value=early,
            ),
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_late",
                return_value="processed prompt",
            ),
            patch(
                "sase.llm_provider.invoke_agent",
                return_value=mock_response,
            ),
            patch(
                "sase.shared_utils.ensure_str_content",
                return_value="response text",
            ),
            patch(
                "sase.xprompt.extract_structured_content",
                return_value=({}, None),
            ),
            patch(
                "sase.xprompt.workflow_executor_steps_prompt.capture_vcs_diff",
                return_value=None,
            ),
        ):
            executor._execute_prompt_step(step, step_state)

        assert step_state.output is not None
        assert step_state.output["diff_path"] == "/tmp/runner.diff"

    @patch("sase.xprompt.workflow_executor_steps_prompt.get_runner_providers")
    def test_runner_meta_propagated(self, mock_get_providers: MagicMock) -> None:
        """PostAgentResult(meta={...}) → propagated to step_state.output."""
        provider = MagicMock(spec=RunnerProvider)
        provider.name = "git"
        provider.pre_agent.return_value = RunnerContext(checkout_target="main")
        provider.post_agent.return_value = PostAgentResult(
            meta={"meta_workspace": "/tmp/ws"}
        )
        mock_get_providers.return_value = {"git": provider}

        executor = _make_prompt_step_executor()
        step = WorkflowStep(name="main", agent="Do work")

        early = _make_mock_early_result(runner=("git", "main", {}))
        mock_response = MagicMock()
        mock_response.content = "response text"

        from sase.xprompt.workflow_models import StepState

        step_state = StepState(name="main")

        with (
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_early",
                return_value=early,
            ),
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_late",
                return_value="processed prompt",
            ),
            patch(
                "sase.llm_provider.invoke_agent",
                return_value=mock_response,
            ),
            patch(
                "sase.shared_utils.ensure_str_content",
                return_value="response text",
            ),
            patch(
                "sase.xprompt.extract_structured_content",
                return_value=({}, None),
            ),
            patch(
                "sase.xprompt.workflow_executor_steps_prompt.capture_vcs_diff",
                return_value=None,
            ),
        ):
            executor._execute_prompt_step(step, step_state)

        assert step_state.output is not None
        assert step_state.output["meta_workspace"] == "/tmp/ws"

    @patch("sase.xprompt.workflow_executor_steps_prompt.get_runner_providers")
    def test_no_runner_directive_no_provider_calls(
        self, mock_get_providers: MagicMock
    ) -> None:
        """No runner directive → no provider interaction."""
        mock_get_providers.return_value = {}

        executor = _make_prompt_step_executor()
        step = WorkflowStep(name="main", agent="Do work")

        early = _make_mock_early_result(runner=None)
        mock_response = MagicMock()
        mock_response.content = "response text"

        from sase.xprompt.workflow_models import StepState

        step_state = StepState(name="main")

        with (
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_early",
                return_value=early,
            ),
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_late",
                return_value="processed prompt",
            ),
            patch(
                "sase.llm_provider.invoke_agent",
                return_value=mock_response,
            ),
            patch(
                "sase.shared_utils.ensure_str_content",
                return_value="response text",
            ),
            patch(
                "sase.xprompt.extract_structured_content",
                return_value=({}, None),
            ),
            patch(
                "sase.xprompt.workflow_executor_steps_prompt.capture_vcs_diff",
                return_value=None,
            ),
        ):
            result = executor._execute_prompt_step(step, step_state)

        assert result is True
        # get_runner_providers should not have been called (no runner directive)
        mock_get_providers.assert_not_called()

    @patch("sase.xprompt.workflow_executor_steps_prompt.get_runner_providers")
    def test_n_and_release_args_parsed(self, mock_get_providers: MagicMock) -> None:
        """named_args {"n": "3", "release": "false"} → pre_agent(ref, n=3, release=False)."""
        provider = MagicMock(spec=RunnerProvider)
        provider.name = "git"
        provider.pre_agent.return_value = RunnerContext(checkout_target="main")
        provider.post_agent.return_value = PostAgentResult()
        mock_get_providers.return_value = {"git": provider}

        executor = _make_prompt_step_executor()
        step = WorkflowStep(name="main", agent="Do work")

        early = _make_mock_early_result(
            runner=("git", "main", {"n": "3", "release": "false"})
        )
        mock_response = MagicMock()
        mock_response.content = "response text"

        from sase.xprompt.workflow_models import StepState

        step_state = StepState(name="main")

        with (
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_early",
                return_value=early,
            ),
            patch(
                "sase.llm_provider.preprocessing.preprocess_prompt_late",
                return_value="processed prompt",
            ),
            patch(
                "sase.llm_provider.invoke_agent",
                return_value=mock_response,
            ),
            patch(
                "sase.shared_utils.ensure_str_content",
                return_value="response text",
            ),
            patch(
                "sase.xprompt.extract_structured_content",
                return_value=({}, None),
            ),
            patch(
                "sase.xprompt.workflow_executor_steps_prompt.capture_vcs_diff",
                return_value=None,
            ),
        ):
            executor._execute_prompt_step(step, step_state)

        provider.pre_agent.assert_called_once_with("main", n=3, release=False)

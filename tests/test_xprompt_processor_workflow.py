"""Tests for WorkflowResult and _flatten_anonymous_workflow."""

from unittest.mock import MagicMock, patch

from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_runner import (
    WorkflowResult,
    _flatten_anonymous_workflow,
)
from sase.xprompt.workflow_models import Workflow, WorkflowStep


# --- WorkflowResult tests ---


def test_workflow_result_construction() -> None:
    """Test basic WorkflowResult dataclass construction."""
    result = WorkflowResult(
        output='{"key": "value"}',
        response_text="Some response",
        artifacts_dir="/tmp/artifacts",
    )
    assert result.output == '{"key": "value"}'
    assert result.response_text == "Some response"
    assert result.artifacts_dir == "/tmp/artifacts"


def test_workflow_result_none_response_text() -> None:
    """Test WorkflowResult with None response_text."""
    result = WorkflowResult(output="", response_text=None, artifacts_dir="/tmp/x")
    assert result.response_text is None


# --- _flatten_anonymous_workflow tests ---


def _make_anonymous_workflow(prompt: str) -> Workflow:
    """Helper to create an anonymous workflow with a single prompt step."""
    return Workflow(
        name="tmp_abc123",
        steps=[WorkflowStep(name="main", agent=prompt)],
    )


def test_flatten_anonymous_workflow_returns_none_for_non_single_step() -> None:
    """Test that multi-step workflows are not flattened."""
    workflow = Workflow(
        name="tmp_abc",
        steps=[
            WorkflowStep(name="step1", agent="first"),
            WorkflowStep(name="step2", agent="second"),
        ],
    )
    result = _flatten_anonymous_workflow(workflow)
    assert result is None


def test_flatten_anonymous_workflow_returns_none_for_non_hash_prompt() -> None:
    """Test that prompts not starting with # are not flattened."""
    workflow = _make_anonymous_workflow("just a plain prompt")
    result = _flatten_anonymous_workflow(workflow)
    assert result is None


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_returns_none_for_unknown_ref(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Test that references to unknown workflows return None."""
    mock_get_all_prompts.return_value = {}
    workflow = _make_anonymous_workflow("#unknown_workflow")
    result = _flatten_anonymous_workflow(workflow)
    assert result is None


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_returns_none_for_prompt_part_ref(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Test that references to simple xprompts (with prompt_part) return None.

    Also verifies the workflow is renamed from its anonymous tmp_* name
    to the real workflow name.
    """
    # A simple xprompt has a prompt_part step, not a prompt step
    simple_xprompt_wf = Workflow(
        name="greeting",
        steps=[WorkflowStep(name="main", prompt_part="Hello {{ name }}")],
    )
    mock_get_all_prompts.return_value = {"greeting": simple_xprompt_wf}
    workflow = _make_anonymous_workflow("#greeting")
    result = _flatten_anonymous_workflow(workflow)
    assert result is None
    assert workflow.name == "greeting"


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_no_rename_for_multi_ref_prompt(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Test that multi-reference prompts don't rename the anonymous workflow.

    When the prompt contains additional # references beyond the first one
    (e.g., '#gh:sase #bd/next'), the workflow should stay anonymous since
    it's an ad-hoc prompt, not a single workflow reference.
    """
    gh_wf = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="GitHub setup: {{ gh_ref }}")],
    )
    mock_get_all_prompts.return_value = {"gh": gh_wf}
    workflow = _make_anonymous_workflow("#gh:sase #bd/next %n:sase-svxv.1")
    result = _flatten_anonymous_workflow(workflow)
    assert result is None
    # Should NOT be renamed to "gh" — this is a multi-reference prompt
    assert workflow.name == "tmp_abc123"


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_returns_workflow_for_pure_multistep(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Test that a pure multi-step workflow reference is flattened."""
    target_wf = Workflow(
        name="split",
        inputs=[InputArg(name="desc", type=InputType.LINE)],
        steps=[
            WorkflowStep(name="analyze", agent="Analyze: {{ desc }}"),
            WorkflowStep(name="execute", agent="Execute based on analysis"),
        ],
    )
    mock_get_all_prompts.return_value = {"split": target_wf}
    workflow = _make_anonymous_workflow("#split")
    result = _flatten_anonymous_workflow(workflow)
    assert result is not None
    ref_wf, pos_args, named_args = result
    assert ref_wf.name == "split"
    assert pos_args == []
    assert named_args == {}

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


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_slow_path_with_xprompt_and_workflow(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Test slow path: xprompt part + standalone workflow in same prompt.

    When a prompt like '#gh:sase #pylimit_split' is used, the fast path
    fails because 'gh' (with colon arg 'sase #pylimit_split') isn't in
    prompts. The slow path should scan all references and find the single
    standalone workflow.
    """
    # gh is an xprompt part (has prompt_part)
    gh_wf = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="GitHub setup: {{ 1 }}")],
    )
    # pylimit_split is a standalone workflow (no prompt_part)
    pylimit_wf = Workflow(
        name="pylimit_split",
        steps=[
            WorkflowStep(name="find_files", bash="echo files=[]"),
            WorkflowStep(name="split_file", agent="Split {{ file_path }}"),
        ],
    )
    mock_get_all_prompts.return_value = {
        "gh": gh_wf,
        "pylimit_split": pylimit_wf,
    }
    workflow = _make_anonymous_workflow("#gh:sase #pylimit_split")
    result = _flatten_anonymous_workflow(workflow)
    assert result is not None
    ref_wf, pos_args, named_args = result
    assert ref_wf.name == "pylimit_split"
    assert pos_args == []
    assert named_args == {}


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_slow_path_no_standalone_workflow(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Test slow path returns None when no standalone workflow is found.

    If all references are xprompt parts (with prompt_part), the slow path
    should return None.
    """
    gh_wf = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="GitHub: {{ 1 }}")],
    )
    context_wf = Workflow(
        name="context",
        steps=[WorkflowStep(name="main", prompt_part="Context setup")],
    )
    mock_get_all_prompts.return_value = {"gh": gh_wf, "context": context_wf}
    workflow = _make_anonymous_workflow("#gh:sase #context")
    result = _flatten_anonymous_workflow(workflow)
    assert result is None


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_slow_path_multiple_standalone_workflows(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Test slow path returns None when multiple standalone workflows found.

    If the prompt contains two or more standalone workflows, we can't
    determine which one to flatten to, so return None.
    """
    wf1 = Workflow(
        name="split",
        steps=[
            WorkflowStep(name="s1", agent="Split"),
            WorkflowStep(name="s2", agent="Do"),
        ],
    )
    wf2 = Workflow(
        name="merge",
        steps=[
            WorkflowStep(name="s1", agent="Merge"),
            WorkflowStep(name="s2", agent="Do"),
        ],
    )
    mock_get_all_prompts.return_value = {"split": wf1, "merge": wf2}
    workflow = _make_anonymous_workflow("#split #merge")
    result = _flatten_anonymous_workflow(workflow)
    assert result is None


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_slow_path_ignores_fenced_code_blocks(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Test slow path ignores workflow references inside fenced code blocks.

    When a standalone workflow reference like #pylimit_split appears inside
    triple-backtick code blocks, it should not be detected as a real workflow
    reference, so the anonymous workflow should not be flattened.
    """
    gh_wf = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="GitHub: {{ 1 }}")],
    )
    pylimit_wf = Workflow(
        name="pylimit_split",
        steps=[
            WorkflowStep(name="find_files", bash="echo files=[]"),
            WorkflowStep(name="split_file", agent="Split {{ file_path }}"),
        ],
    )
    mock_get_all_prompts.return_value = {
        "gh": gh_wf,
        "pylimit_split": pylimit_wf,
    }
    prompt = (
        "#gh:sase Some text about the pylimit_split workflow.\n"
        "\n"
        "```\n"
        'sase run "#gh:sase #pylimit_split(1000 850 666)"\n'
        "```\n"
    )
    workflow = _make_anonymous_workflow(prompt)
    result = _flatten_anonymous_workflow(workflow)
    # Should NOT flatten — the only standalone workflow ref is inside a code block
    assert result is None


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_slow_path_with_args(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Test slow path parses arguments for the standalone workflow reference."""
    gh_wf = Workflow(
        name="gh",
        steps=[WorkflowStep(name="main", prompt_part="GitHub: {{ 1 }}")],
    )
    target_wf = Workflow(
        name="deploy",
        inputs=[InputArg(name="env", type=InputType.WORD)],
        steps=[
            WorkflowStep(name="build", bash="make build"),
            WorkflowStep(name="push", agent="Deploy to {{ env }}"),
        ],
    )
    mock_get_all_prompts.return_value = {"gh": gh_wf, "deploy": target_wf}
    workflow = _make_anonymous_workflow("#gh:sase #deploy:prod")
    result = _flatten_anonymous_workflow(workflow)
    assert result is not None
    ref_wf, pos_args, named_args = result
    assert ref_wf.name == "deploy"
    assert pos_args == ["prod"]
    assert named_args == {}

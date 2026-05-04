"""Tests for WorkflowResult, _flatten_anonymous_workflow, and execute_workflow."""

import warnings
from unittest.mock import MagicMock, patch

import pytest

from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_runner import (
    _WORKFLOW_HITL_OVERRIDE_ARG,
    _WORKFLOW_INHERITED_VCS_TAG_ARG,
    _WORKFLOW_MODEL_OVERRIDE_ARG,
    WorkflowResult,
    _flatten_anonymous_workflow,
    execute_workflow,
)
from sase.xprompt.workflow_models import Workflow, WorkflowStep, WorkflowValidationError


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
def test_flatten_anonymous_workflow_accepts_explicit_standalone_marker(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Explicit #! references flatten without compatibility warnings."""
    target_wf = Workflow(
        name="split",
        inputs=[InputArg(name="desc", type=InputType.LINE)],
        steps=[WorkflowStep(name="analyze", agent="Analyze: {{ desc }}")],
    )
    mock_get_all_prompts.return_value = {"split": target_wf}
    workflow = _make_anonymous_workflow("#!split:prod")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _flatten_anonymous_workflow(workflow)

    assert caught == []
    assert result is not None
    ref_wf, pos_args, named_args = result
    assert ref_wf.name == "split"
    assert pos_args == ["prod"]
    assert named_args == {}


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_preserves_explicit_hitl_override(
    mock_get_all_prompts: MagicMock,
) -> None:
    """#!workflow!! carries the HITL override into execute_workflow."""
    target_wf = Workflow(
        name="sync",
        steps=[WorkflowStep(name="run", bash="echo sync")],
    )
    mock_get_all_prompts.return_value = {"sync": target_wf}
    workflow = _make_anonymous_workflow("#!sync!!")

    result = _flatten_anonymous_workflow(workflow)

    assert result is not None
    ref_wf, pos_args, named_args = result
    assert ref_wf.name == "sync"
    assert pos_args == []
    assert named_args == {_WORKFLOW_HITL_OVERRIDE_ARG: "1"}


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_warns_for_legacy_standalone_marker(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Bare #standalone still works during compatibility but warns."""
    target_wf = Workflow(
        name="split",
        steps=[WorkflowStep(name="analyze", agent="Analyze")],
    )
    mock_get_all_prompts.return_value = {"split": target_wf}
    workflow = _make_anonymous_workflow("#split")

    with pytest.warns(UserWarning, match="use '#!split'"):
        result = _flatten_anonymous_workflow(workflow)

    assert result is not None
    assert result[0].name == "split"


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_rejects_bang_for_embeddable(
    mock_get_all_prompts: MagicMock,
) -> None:
    """#! is reserved for workflows with no prompt_part."""
    commit_wf = Workflow(
        name="commit",
        steps=[WorkflowStep(name="main", prompt_part="Commit context")],
    )
    mock_get_all_prompts.return_value = {"commit": commit_wf}
    workflow = _make_anonymous_workflow("#!commit")

    with pytest.raises(WorkflowValidationError, match="Only standalone workflows"):
        _flatten_anonymous_workflow(workflow)


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
def test_flatten_anonymous_workflow_slow_path_prefers_explicit_standalone(
    mock_get_all_prompts: MagicMock,
) -> None:
    """When both legacy and explicit refs exist, #! selects the workflow."""
    legacy_wf = Workflow(
        name="legacy",
        steps=[WorkflowStep(name="run", agent="Legacy")],
    )
    explicit_wf = Workflow(
        name="explicit",
        steps=[WorkflowStep(name="run", agent="Explicit")],
    )
    mock_get_all_prompts.return_value = {
        "legacy": legacy_wf,
        "explicit": explicit_wf,
    }
    workflow = _make_anonymous_workflow("#legacy #!explicit")

    result = _flatten_anonymous_workflow(workflow)

    assert result is not None
    assert result[0].name == "explicit"


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
    with pytest.raises(WorkflowValidationError, match="Ambiguous standalone"):
        _flatten_anonymous_workflow(workflow)


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
        "sase run '#gh:sase #!pylimit_split(1000 850 666)'\n"
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


@patch("sase.xprompt.loader.get_all_prompts")
def test_flatten_anonymous_workflow_preserves_wrapper_model_directive(
    mock_get_all_prompts: MagicMock,
) -> None:
    """Wrapper-level %model should be forwarded when flattening."""
    target_wf = Workflow(
        name="split",
        steps=[
            WorkflowStep(name="analyze", agent="Analyze"),
            WorkflowStep(name="execute", agent="Execute"),
        ],
    )
    mock_get_all_prompts.return_value = {"split": target_wf}
    workflow = _make_anonymous_workflow("#split %model:gemini-3-flash-preview")

    result = _flatten_anonymous_workflow(workflow)

    assert result is not None
    ref_wf, pos_args, named_args = result
    assert ref_wf.name == "split"
    assert pos_args == []
    assert named_args == {
        _WORKFLOW_MODEL_OVERRIDE_ARG: "gemini-3-flash-preview",
    }


# --- execute_workflow flattening tests ---


@patch("sase.xprompt.loader.get_all_prompts")
@patch("sase.xprompt.workflow_executor.WorkflowExecutor")
def test_execute_workflow_flatten_preserves_caller_named_args(
    mock_workflow_executor: MagicMock,
    mock_get_all_prompts: MagicMock,
) -> None:
    """Anonymous flattening should preserve caller-injected context keys."""
    target_wf = Workflow(
        name="split",
        steps=[WorkflowStep(name="setup", bash="echo setup")],
    )
    mock_get_all_prompts.return_value = {"split": target_wf}

    executor_instance = mock_workflow_executor.return_value
    executor_instance.execute.return_value = True
    executor_instance.state.steps = []

    anon_wf = _make_anonymous_workflow("#split")
    execute_workflow(
        name=anon_wf.name,
        positional_args=[],
        named_args={
            "cl_name": "my_feature",
            "project_file": "/tmp/myproj.gp",
            "workspace_num": 101,
        },
        workflow_obj=anon_wf,
        silent=True,
    )

    called_args = mock_workflow_executor.call_args.kwargs["args"]
    assert called_args["cl_name"] == "my_feature"
    assert called_args["project_file"] == "/tmp/myproj.gp"
    assert called_args["workspace_num"] == 101


@patch("sase.xprompt.loader.get_all_prompts")
@patch("sase.xprompt.workflow_executor.WorkflowExecutor")
def test_execute_workflow_flatten_explicit_named_args_override_caller(
    mock_workflow_executor: MagicMock,
    mock_get_all_prompts: MagicMock,
) -> None:
    """Args from #workflow(...) should override same-name caller defaults."""
    target_wf = Workflow(
        name="split",
        steps=[WorkflowStep(name="setup", bash="echo setup")],
    )
    mock_get_all_prompts.return_value = {"split": target_wf}

    executor_instance = mock_workflow_executor.return_value
    executor_instance.execute.return_value = True
    executor_instance.state.steps = []

    anon_wf = _make_anonymous_workflow("#split(cl_name=explicit_cl)")
    execute_workflow(
        name=anon_wf.name,
        positional_args=[],
        named_args={
            "cl_name": "implicit_cl",
            "workspace_num": 100,
        },
        workflow_obj=anon_wf,
        silent=True,
    )

    called_args = mock_workflow_executor.call_args.kwargs["args"]
    assert called_args["cl_name"] == "explicit_cl"
    assert called_args["workspace_num"] == 100


@patch("sase.xprompt.loader.get_all_prompts")
@patch("sase.xprompt.workflow_executor.WorkflowExecutor")
def test_execute_workflow_flatten_preserves_wrapper_model_override(
    mock_workflow_executor: MagicMock,
    mock_get_all_prompts: MagicMock,
) -> None:
    """Wrapper %model survives flattening and is passed as inherited override."""
    target_wf = Workflow(
        name="split",
        steps=[WorkflowStep(name="setup", bash="echo setup")],
    )
    mock_get_all_prompts.return_value = {"split": target_wf}

    executor_instance = mock_workflow_executor.return_value
    executor_instance.execute.return_value = True
    executor_instance.state.steps = []

    anon_wf = _make_anonymous_workflow("#split %model:gemini-3-flash-preview")
    execute_workflow(
        name=anon_wf.name,
        positional_args=[],
        named_args={"cl_name": "my_feature"},
        workflow_obj=anon_wf,
        silent=True,
    )

    call_kwargs = mock_workflow_executor.call_args.kwargs
    assert call_kwargs["inherited_model_override"] == "gemini-3-flash-preview"
    assert _WORKFLOW_MODEL_OVERRIDE_ARG not in call_kwargs["args"]
    assert call_kwargs["args"]["cl_name"] == "my_feature"


@patch("sase.xprompt.loader.get_all_prompts")
@patch("sase.xprompt.workflow_executor.WorkflowExecutor")
def test_execute_workflow_passes_inherited_vcs_tag_without_context_leak(
    mock_workflow_executor: MagicMock,
    mock_get_all_prompts: MagicMock,
) -> None:
    """Inherited VCS metadata reaches the executor but not workflow args."""
    target_wf = Workflow(
        name="split",
        steps=[WorkflowStep(name="setup", bash="echo setup")],
    )
    mock_get_all_prompts.return_value = {"split": target_wf}

    executor_instance = mock_workflow_executor.return_value
    executor_instance.execute.return_value = True
    executor_instance.state.steps = []

    anon_wf = _make_anonymous_workflow("#split")
    execute_workflow(
        name=anon_wf.name,
        positional_args=[],
        named_args={
            "cl_name": "my_feature",
            _WORKFLOW_INHERITED_VCS_TAG_ARG: "#gh:sase ",
        },
        workflow_obj=anon_wf,
        silent=True,
    )

    call_kwargs = mock_workflow_executor.call_args.kwargs
    assert call_kwargs["inherited_vcs_tag"] == "#gh:sase "
    assert _WORKFLOW_INHERITED_VCS_TAG_ARG not in call_kwargs["args"]
    assert call_kwargs["args"]["cl_name"] == "my_feature"


@patch("sase.xprompt.workflow_executor.WorkflowExecutor")
def test_execute_workflow_inherited_vcs_tag_not_visible_to_simple_xprompt_template(
    mock_workflow_executor: MagicMock,
) -> None:
    """Internal VCS metadata is stripped before prompt_part rendering."""
    simple_wf = Workflow(
        name="simple",
        steps=[
            WorkflowStep(
                name="main",
                prompt_part=(
                    "{{ __sase_workflow_inherited_vcs_tag is defined }} {{ topic }}"
                ),
            )
        ],
    )

    executor_instance = mock_workflow_executor.return_value
    executor_instance.execute.return_value = True
    executor_instance.state.steps = []

    execute_workflow(
        name=simple_wf.name,
        positional_args=[],
        named_args={
            "topic": "visible",
            _WORKFLOW_INHERITED_VCS_TAG_ARG: "#gh:sase ",
        },
        workflow_obj=simple_wf,
        silent=True,
    )

    call_kwargs = mock_workflow_executor.call_args.kwargs
    assert call_kwargs["inherited_vcs_tag"] == "#gh:sase "
    assert call_kwargs["workflow"].steps[0].agent == "false visible"
    assert _WORKFLOW_INHERITED_VCS_TAG_ARG not in call_kwargs["args"]


# --- _resolve_vcs_cwd tests ---


@patch("sase.xprompt.loader.detect_project")
@patch("os.chdir")
@patch("sase.workspace_provider.resolve_ref")
@patch("sase.workspace_provider.get_workflow_names")
@patch("sase.xprompt._parsing.normalize_vcs_underscore_refs", side_effect=lambda q: q)
def test_resolve_vcs_cwd_returns_vcs_ref(
    _mock_normalize: MagicMock,
    mock_get_wf_names: MagicMock,
    mock_resolve_ref: MagicMock,
    _mock_chdir: MagicMock,
    _mock_detect_project: MagicMock,
) -> None:
    """_resolve_vcs_cwd returns (project_name, vcs_ref) with the raw ref."""
    from sase.main.query_handler._query import _resolve_vcs_cwd

    mock_get_wf_names.return_value = ["hg"]
    resolved = MagicMock()
    resolved.primary_workspace_dir = "/some/workspace"
    resolved.project_name = "yserve"
    mock_resolve_ref.return_value = resolved

    result = _resolve_vcs_cwd("#hg:yserve_batch_create_update #split")

    assert result is not None
    project_name, vcs_ref = result
    assert project_name == "yserve"
    assert vcs_ref == "yserve_batch_create_update"


@patch("sase.xprompt.loader.detect_project")
@patch("os.chdir")
@patch("sase.workspace_provider.resolve_ref")
@patch("sase.workspace_provider.get_workflow_names")
@patch("sase.xprompt._parsing.normalize_vcs_underscore_refs", side_effect=lambda q: q)
def test_resolve_vcs_cwd_falls_back_to_ref_as_project_name(
    _mock_normalize: MagicMock,
    mock_get_wf_names: MagicMock,
    mock_resolve_ref: MagicMock,
    _mock_chdir: MagicMock,
    _mock_detect_project: MagicMock,
) -> None:
    """When project_name is None, _resolve_vcs_cwd uses ref as the first element."""
    from sase.main.query_handler._query import _resolve_vcs_cwd

    mock_get_wf_names.return_value = ["gh"]
    resolved = MagicMock()
    resolved.primary_workspace_dir = "/some/workspace"
    resolved.project_name = None  # resolution doesn't know the project name
    mock_resolve_ref.return_value = resolved

    result = _resolve_vcs_cwd("#gh:my_feature_branch")

    assert result is not None
    project_name, vcs_ref = result
    # Falls back to the ref itself as project name
    assert project_name == "my_feature_branch"
    # vcs_ref is always the raw ref
    assert vcs_ref == "my_feature_branch"


@patch("sase.xprompt.loader.detect_project")
@patch("os.chdir")
@patch("sase.workspace_provider.resolve_ref")
@patch("sase.workspace_provider.get_workflow_names")
@patch("sase.xprompt._parsing.normalize_vcs_underscore_refs", side_effect=lambda q: q)
def test_resolve_vcs_cwd_returns_ref_when_workflow_type_not_registered(
    _mock_normalize: MagicMock,
    mock_get_wf_names: MagicMock,
    mock_resolve_ref: MagicMock,
    mock_chdir: MagicMock,
    mock_detect_project: MagicMock,
) -> None:
    """Unregistered #type:ref still returns (ref, ref) without chdir."""
    from sase.main.query_handler._query import _resolve_vcs_cwd

    mock_get_wf_names.return_value = ["gh", "git"]

    result = _resolve_vcs_cwd("#hg:yserve_batch_create_update #split")

    assert result == ("yserve_batch_create_update", "yserve_batch_create_update")
    mock_resolve_ref.assert_not_called()
    mock_chdir.assert_not_called()
    mock_detect_project.cache_clear.assert_not_called()

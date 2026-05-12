"""Tests for execute_workflow behavior around workflow flattening."""

from unittest.mock import MagicMock, patch

from sase.xprompt.workflow_runner import (
    _WORKFLOW_INHERITED_VCS_TAG_ARG,
    _WORKFLOW_MODEL_OVERRIDE_ARG,
    execute_workflow,
)
from sase.xprompt.workflow_models import StepState, StepStatus, Workflow, WorkflowStep


def _make_anonymous_workflow(prompt: str) -> Workflow:
    """Helper to create an anonymous workflow with a single prompt step."""
    return Workflow(
        name="tmp_abc123",
        steps=[WorkflowStep(name="main", agent=prompt)],
    )


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
            "project_file": "/tmp/myproj.sase",
            "workspace_num": 101,
        },
        workflow_obj=anon_wf,
        silent=True,
    )

    called_args = mock_workflow_executor.call_args.kwargs["args"]
    assert called_args["cl_name"] == "my_feature"
    assert called_args["project_file"] == "/tmp/myproj.sase"
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


@patch("sase.xprompt.workflow_executor.WorkflowExecutor")
def test_execute_workflow_response_text_uses_latest_completed_raw_step(
    mock_workflow_executor: MagicMock,
) -> None:
    """Post-agent steps should not erase the transcript response text."""
    workflow = Workflow(
        name="refresh_docs",
        steps=[
            WorkflowStep(name="run_docs", agent="Update docs"),
            WorkflowStep(name="update_marker", bash="touch marker"),
        ],
    )

    executor_instance = mock_workflow_executor.return_value
    executor_instance.execute.return_value = True
    executor_instance.state.steps = [
        StepState(
            name="run_docs",
            status=StepStatus.COMPLETED,
            output={"_raw": "agent response"},
        ),
        StepState(
            name="update_marker",
            status=StepStatus.COMPLETED,
            output={"marker": "updated"},
        ),
    ]

    result = execute_workflow(
        name=workflow.name,
        positional_args=[],
        named_args={},
        workflow_obj=workflow,
        silent=True,
    )

    assert result.response_text == "agent response"
    assert result.output == '{\n  "marker": "updated"\n}'

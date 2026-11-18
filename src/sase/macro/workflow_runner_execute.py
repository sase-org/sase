"""Workflow execution, failed-state writing, and embedding expansion."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

from ._workflow_runner_args import (
    WORKFLOW_HITL_OVERRIDE_ARG,
    WORKFLOW_INHERITED_VCS_TAG_ARG,
    WORKFLOW_MODEL_OVERRIDE_ARG,
)
from .input_binding import InputBindingError, bind_input_args
from .workflow_executor_types import WorkflowSuspended
from .workflow_models import (
    StepStatus,
    WorkflowExecutionError,
    WorkflowStep,
    WorkflowValidationError,
)
from .workflow_runner_flatten import flatten_anonymous_workflow

if TYPE_CHECKING:
    from .workflow_models import Workflow

__all__ = [
    "WorkflowResult",
    "execute_workflow",
    "expand_workflow_for_embedding",
]


def _bind_workflow_args(
    workflow: "Workflow",
    positional_args: list[str],
    named_args: dict[str, Any],
) -> dict[str, Any]:
    try:
        return bind_input_args(workflow.inputs, positional_args, named_args).values
    except InputBindingError as exc:
        raise WorkflowExecutionError(
            f"Workflow '#{workflow.name}' argument error: {exc}"
        ) from exc


def _write_failed_workflow_state(
    workflow_name: str,
    artifacts_dir: str,
    error_message: str,
    workflow: "Workflow | None" = None,
) -> None:
    """Write a workflow_state.json for validation failures.

    This ensures that the TUI can display the error when a workflow fails
    validation before execution starts.

    Args:
        workflow_name: The workflow name.
        artifacts_dir: Directory for workflow artifacts.
        error_message: The validation error message.
        workflow: Optional workflow object to extract step prompts from.
    """
    import json
    import os

    from sase.core.time import local_now

    # Save agent templates from step definitions so the TUI can display
    # the prompt that was attempted even when no steps ran.
    step_prompts: list[dict[str, str]] = []
    if workflow is not None:
        for step in workflow.steps:
            if step.agent:
                step_prompts.append({"name": step.name, "agent": step.agent})

    state_dict: dict[str, Any] = {
        "workflow_name": workflow_name,
        "status": "failed",
        "current_step_index": 0,
        "steps": [],
        "context": {},
        "artifacts_dir": artifacts_dir,
        "start_time": local_now().isoformat(),
        "pid": os.getpid(),
        "error": error_message,
        "is_anonymous": workflow_name.startswith("tmp_"),
        "hidden": bool(workflow.hidden) if workflow is not None else False,
    }
    if step_prompts:
        state_dict["step_prompts"] = step_prompts
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_dict, f, indent=2)
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)


@dataclass
class WorkflowResult:
    """Result from executing a workflow.

    Attributes:
        output: JSON string of the last step's output.
        response_text: Newest raw response text from a completed prompt step, if any.
        artifacts_dir: Path to the artifacts directory.
        continuation_prepared_ref: Ref for the last prepared local prompt capture.
        suspension: Staged review that paused the workflow, when present.
    """

    output: str
    response_text: str | None
    artifacts_dir: str
    continuation_prepared_ref: str | None = None
    suspension: WorkflowSuspended | None = None


def execute_workflow(
    name: str,
    positional_args: list[str],
    named_args: dict[str, Any],
    artifacts_dir: str | None = None,
    *,
    silent: bool = False,
    project: str | None = None,
    workflow_obj: "Workflow | None" = None,
    hitl_override: bool | None = None,
    workspace_rebind_callback: Callable[[dict[str, Any], str], None] | None = None,
    authored_local_request: str | None = None,
    continuation_segments: Sequence[Any] = (),
) -> WorkflowResult:
    """Execute a workflow and return its result.

    Args:
        name: The workflow name (can be a workflow or converted macro).
        positional_args: Positional arguments.
        named_args: Named arguments.
        artifacts_dir: Optional directory for workflow artifacts.
        silent: If True, disable console output and use auto-approve for HITL.
            Use this when running workflows from non-interactive contexts (e.g., TUI).
        project: Optional project name for loading prompts.
        workflow_obj: Optional pre-built Workflow object (e.g., anonymous workflows).
            When provided, skips the name-based lookup.
        hitl_override: Force HITL on (True) or off (False) for all steps,
            overriding individual step ``hitl`` settings.  None preserves
            per-step behavior.
        workspace_rebind_callback: Optional hook invoked when a script step
            changes into a known SASE workspace.

    Returns:
        WorkflowResult with output, response text, and artifacts directory.

    Raises:
        WorkflowExecutionError: If workflow execution fails.
    """
    import json
    import os
    import tempfile
    from typing import Any

    from ._step_input_loader import load_step_input_value
    from .loader import get_all_prompts
    from .workflow_executor import WorkflowExecutor
    from .workflow_hitl import CLIHITLHandler, TUIHITLHandler
    from .workflow_output import WorkflowOutputHandler
    from .workflow_validator import validate_workflow

    if workflow_obj is not None:
        workflow = workflow_obj
    else:
        # Use unified loader to get both workflows and converted macros
        prompts = get_all_prompts(project=project)
        if name not in prompts:
            from sase.macro.local_trust import blocked_local_macro_message

            blocked = blocked_local_macro_message(name, project=project)
            if blocked:
                raise WorkflowExecutionError(blocked)
            raise WorkflowExecutionError(f"Workflow '{name}' not found")
        from sase.macro.local_trust import blocked_local_macro_message

        blocked = blocked_local_macro_message(
            name,
            catalog_item=prompts[name],
            project=project,
        )
        if blocked:
            raise WorkflowExecutionError(blocked)
        workflow = prompts[name]

    # Create artifacts_dir early so we can write state on validation failure
    if artifacts_dir is None:
        from sase.core.paths import get_sase_managed_tmpdir

        artifacts_dir = tempfile.mkdtemp(
            prefix=f"workflow-{name}-",
            dir=get_sase_managed_tmpdir("workflow-artifacts"),
        )
    else:
        os.makedirs(artifacts_dir, exist_ok=True)

    # Caller-injected workflow metadata must not be visible to templates,
    # state, or declared workflow inputs.
    inherited_vcs_tag: str | None = None
    if WORKFLOW_INHERITED_VCS_TAG_ARG in named_args:
        inherited_vcs_tag = str(named_args[WORKFLOW_INHERITED_VCS_TAG_ARG])
        named_args = {
            k: v for k, v in named_args.items() if k != WORKFLOW_INHERITED_VCS_TAG_ARG
        }

    # Handle simple macros: convert prompt_part to prompt step so they go
    # through WorkflowExecutor (producing workflow_state.json and markers).
    # Rendered here with a shared source boundary, then marked pre-rendered
    # so the executor skips its source passes instead of presenting rendered
    # text (which now holds literal data commands) as fresh source — and
    # instead of executing the authored command a second time.
    if workflow.is_simple_macro():
        from sase.macro._trace import ExpansionTrace
        from sase.macro.workflow_executor_utils import (
            mark_step_pre_rendered,
            render_workflow_template_with_directives,
        )
        from sase.macro.workflow_models import Workflow as WfModel

        render_ctx = _bind_workflow_args(workflow, positional_args, named_args)

        content = workflow.get_prompt_part_content()
        simple_trace = ExpansionTrace()
        rendered, simple_directives = render_workflow_template_with_directives(
            content, render_ctx, trace=simple_trace
        )
        main_step = WorkflowStep(name="main", agent=rendered)
        from sase.artifact_ref_prompt_context import prompt_segment_vcs_refs

        mark_step_pre_rendered(
            main_step,
            content,
            segment_vcs_refs=prompt_segment_vcs_refs(content),
            trace=simple_trace,
            directives=simple_directives,
        )
        workflow = WfModel(
            name=workflow.name,
            inputs=[],
            steps=[main_step],
            source_path=workflow.source_path,
            macros=workflow.macros,
        )

    # Flatten anonymous workflows that wrap a single multi-step workflow
    # reference (e.g., "sase run '#split(...)'" → execute split directly)
    if workflow.is_anonymous():
        flattened = flatten_anonymous_workflow(workflow, project=project)
        if flattened is not None:
            workflow, positional_args, flattened_named = flattened
            named_args = {**named_args, **flattened_named}
        # Sync name — _flatten may rename the workflow even when not flattening
        # (e.g., prompt_part workflows like #fork_by_chat get named but not replaced)
        name = workflow.name

    # Compile-time validation with error state on failure
    try:
        validate_workflow(workflow)
    except WorkflowValidationError as e:
        _write_failed_workflow_state(
            workflow_name=name,
            artifacts_dir=artifacts_dir,
            error_message=str(e),
            workflow=workflow,
        )
        raise

    # Extract wrapper-level model override (injected during anonymous
    # workflow flattening) before building the workflow context.
    inherited_model_override: str | None = None
    if WORKFLOW_MODEL_OVERRIDE_ARG in named_args:
        inherited_model_override = str(named_args[WORKFLOW_MODEL_OVERRIDE_ARG])
        named_args = {
            k: v for k, v in named_args.items() if k != WORKFLOW_MODEL_OVERRIDE_ARG
        }
    if WORKFLOW_HITL_OVERRIDE_ARG in named_args:
        hitl_value = str(named_args[WORKFLOW_HITL_OVERRIDE_ARG])
        hitl_override = hitl_value == "1"
        named_args = {
            k: v for k, v in named_args.items() if k != WORKFLOW_HITL_OVERRIDE_ARG
        }
    if WORKFLOW_INHERITED_VCS_TAG_ARG in named_args:
        inherited_vcs_tag = str(named_args[WORKFLOW_INHERITED_VCS_TAG_ARG])
        named_args = {
            k: v for k, v in named_args.items() if k != WORKFLOW_INHERITED_VCS_TAG_ARG
        }

    args = _bind_workflow_args(workflow, positional_args, named_args)

    # Process step inputs: load from @file or parse inline YAML/JSON
    # Step inputs allow users to skip steps by providing their outputs directly
    processed_args: dict[str, Any] = dict(args)
    for input_arg in workflow.inputs:
        if input_arg.name not in args:
            continue
        value = args[input_arg.name]
        if input_arg.is_step_input:
            # Load and validate step input
            processed_args[input_arg.name] = load_step_input_value(
                value, input_arg.output_schema
            )
        # Non-step-input args are already preserved from dict(args)
    args = processed_args

    # Create handlers based on silent mode
    # Suppress workflow output for single-step anonymous workflows
    # (e.g., "sase run hello" shouldn't show "[Step 1/1: main]")
    is_anonymous_single_step = workflow.is_anonymous() and len(workflow.steps) == 1

    hitl_handler: TUIHITLHandler | CLIHITLHandler
    if silent:
        hitl_handler = TUIHITLHandler(artifacts_dir, workflow_name=name)
        output_handler = None
    elif is_anonymous_single_step:
        hitl_handler = CLIHITLHandler()
        output_handler = None
    else:
        hitl_handler = CLIHITLHandler()
        output_handler = WorkflowOutputHandler()

    # Create and run executor
    executor = WorkflowExecutor(
        workflow=workflow,
        args=args,
        artifacts_dir=artifacts_dir,
        hitl_handler=hitl_handler,
        output_handler=output_handler,
        hitl_override=hitl_override,
        inherited_model_override=inherited_model_override,
        inherited_vcs_tag=inherited_vcs_tag,
        workspace_rebind_callback=workspace_rebind_callback,
        authored_local_request=authored_local_request,
        continuation_segments=continuation_segments,
    )

    execution = executor.execute()

    if isinstance(execution, WorkflowSuspended):
        return WorkflowResult(
            output="",
            response_text=execution.provider_content,
            artifacts_dir=artifacts_dir,
            continuation_prepared_ref=None,
            suspension=execution,
        )

    if not execution:
        raise WorkflowExecutionError(f"Workflow '{name}' was rejected or failed")

    # Extract output and response text
    output_str = ""
    response_text: str | None = None
    if executor.state.steps:
        last_step = executor.state.steps[-1]
        if last_step.output:
            output_str = json.dumps(last_step.output, indent=2)

        for step_state in reversed(executor.state.steps):
            if step_state.status is not StepStatus.COMPLETED:
                continue
            if not isinstance(step_state.output, dict):
                continue
            raw_response = step_state.output.get("_raw")
            if isinstance(raw_response, str) and raw_response:
                response_text = raw_response
                break

    from sase.continuation_capture import read_prepared_prompt_capture_ref

    return WorkflowResult(
        output=output_str,
        response_text=response_text,
        artifacts_dir=artifacts_dir,
        continuation_prepared_ref=read_prepared_prompt_capture_ref(artifacts_dir),
    )


def expand_workflow_for_embedding(
    workflow_name: str,
    positional_args: list[str],
    named_args: dict[str, Any],
) -> tuple[str, list[WorkflowStep], list[WorkflowStep]]:
    """Expand a workflow for embedding into a containing prompt.

    When a workflow with a `prompt_part` step is embedded in a prompt,
    this function extracts:
    - The rendered prompt_part content (to append to the containing prompt)
    - Pre-steps (steps before prompt_part) to execute before the prompt
    - Post-steps (steps after prompt_part) to execute after the prompt

    If the workflow has no prompt_part, all steps are returned as post-steps.

    Args:
        workflow_name: The name of the workflow to expand.
        positional_args: Positional arguments for the workflow.
        named_args: Named arguments for the workflow.

    Returns:
        Tuple of (prompt_part_content, pre_steps, post_steps).

    Raises:
        WorkflowValidationError: If workflow not found.
    """
    from sase.macro.workflow_executor_utils import render_prompt_template

    from .loader import get_all_workflows

    workflows = get_all_workflows()
    if workflow_name not in workflows:
        raise WorkflowValidationError(f"Workflow '{workflow_name}' not found")

    workflow = workflows[workflow_name]

    args = _bind_workflow_args(workflow, positional_args, named_args)

    # Get pre and post steps
    pre_steps = workflow.get_pre_prompt_steps()
    post_steps = workflow.get_post_prompt_steps()

    # Render prompt_part content with args as initial context
    # Note: Pre-step outputs will be added to context during execution
    prompt_part_content = workflow.get_prompt_part_content()
    if prompt_part_content:
        # Render with just the input args for now
        # The full context (with pre-step outputs) will be used at execution time
        # when the prompt_part is actually expanded
        prompt_part_content = render_prompt_template(prompt_part_content, args)

    return prompt_part_content, pre_steps, post_steps

"""Workflow execution and embedding for xprompt workflows."""

import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ._parsing import (
    find_double_colon_text_end,
    find_matching_paren_for_args,
    find_shorthand_text_end,
    parse_args,
    parse_workflow_reference,
)
from .loader import get_all_workflows
from .models import UNSET
from .workflow_models import WorkflowStep, WorkflowValidationError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .workflow_models import Workflow

# Pattern to match workflow/xprompt references in prompts (same as processor.py)
_REF_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"(?:(\()|:(`[^`]*`|\$\([^)]*\)|[a-zA-Z0-9_.~/-]*[a-zA-Z0-9_~/-])|(\+))?"
)

_WORKFLOW_MODEL_OVERRIDE_ARG = "__sase_workflow_model_override"


def is_workflow_reference(name: str) -> bool:
    """Check if a name refers to a workflow.

    Args:
        name: The xprompt/workflow name to check.

    Returns:
        True if the name matches a workflow, False otherwise.
    """
    workflows = get_all_workflows()
    return name in workflows


def _find_standalone_workflow_ref(
    prompt_text: str,
    prompts: "dict[str, Workflow]",
) -> "tuple[Workflow, list[str], dict[str, str]] | None":
    """Scan prompt text for exactly one standalone (no prompt_part) workflow ref.

    Used as a fallback when the fast-path single-reference check in
    ``_flatten_anonymous_workflow`` fails. The prompt may contain multiple
    ``#name`` references — some xprompt parts, some workflows with
    ``prompt_part`` — but if exactly one is a pure multi-step workflow
    (no ``prompt_part``), return it with its parsed arguments.

    Args:
        prompt_text: The full prompt text to scan.
        prompts: The combined prompts dict (xprompts + workflows).

    Returns:
        Tuple of (workflow, positional_args, named_args) if exactly one
        standalone workflow was found, None otherwise.
    """
    from ._fenced_blocks import protect_fenced_blocks

    # Protect fenced code blocks so that references inside triple-backtick
    # blocks are not mistaken for real workflow references.
    fenced_blocks: list[str] = []
    protected_text = protect_fenced_blocks(prompt_text, fenced_blocks)

    matches = list(re.finditer(_REF_PATTERN, protected_text, re.MULTILINE))

    standalone_refs: list[tuple[str, re.Match[str]]] = []
    for match in matches:
        name = match.group(1)
        if name in prompts and not prompts[name].has_prompt_part():
            standalone_refs.append((name, match))

    if len(standalone_refs) != 1:
        return None

    wf_name, match = standalone_refs[0]
    referenced = prompts[wf_name]

    # Parse arguments for this specific reference
    has_open_paren = match.group(2) is not None
    colon_arg = match.group(3)
    plus_suffix = match.group(4)

    positional_args: list[str] = []
    named_args: dict[str, str] = {}

    if has_open_paren:
        paren_start = match.end() - 1
        paren_end = find_matching_paren_for_args(protected_text, paren_start)
        if paren_end is not None:
            paren_content = protected_text[paren_start + 1 : paren_end]
            positional_args, named_args = parse_args(paren_content)
    elif colon_arg is not None:
        if colon_arg.startswith("`") and colon_arg.endswith("`"):
            colon_arg = colon_arg[1:-1]
        positional_args = [colon_arg]
    elif plus_suffix is not None:
        positional_args = ["true"]
    else:
        # Check for :: or : shorthand after the reference. The regex
        # doesn't capture double-colon syntax (#name:: text), so we
        # handle it here by looking at the original (unprotected) text.
        # Positions are safe to reuse because protect_fenced_blocks
        # preserves string length.
        after_match = prompt_text[match.end() :]
        if after_match.startswith(":: "):
            text_start = match.end() + 3
            text_end = find_double_colon_text_end(prompt_text, text_start)
            text = prompt_text[text_start:text_end].rstrip()
            if text:
                positional_args = [text]
        elif after_match.startswith(": "):
            text_start = match.end() + 2
            text_end = find_shorthand_text_end(prompt_text, text_start)
            text = prompt_text[text_start:text_end].rstrip()
            if text:
                positional_args = [text]

    return referenced, positional_args, named_args


def _flatten_anonymous_workflow(
    workflow: "Workflow",
    project: str | None = None,
) -> "tuple[Workflow, list[str], dict[str, str]] | None":
    """Flatten an anonymous workflow that wraps a single workflow reference.

    If the anonymous workflow's single prompt step is entirely a ``#name(args)``
    reference to a pure multi-step workflow (one without a prompt_part), return
    that referenced workflow with the parsed args. Otherwise return None.

    Also handles the case where the prompt contains multiple references (e.g.,
    ``#gh:sase #pylimit_split``) where some are xprompt parts and exactly one
    is a standalone workflow (no prompt_part). In that case, the standalone
    workflow is extracted and flattened.

    Args:
        workflow: The anonymous workflow to check.
        project: Optional project name for loading prompts.

    Returns:
        Tuple of (referenced_workflow, positional_args, named_args) if
        flattening is appropriate, None otherwise.
    """
    from .loader import get_all_prompts

    # Only flatten single-step agent workflows
    if len(workflow.steps) != 1 or not workflow.steps[0].is_agent_step():
        return None

    prompt_text = (workflow.steps[0].agent or "").strip()

    # Must contain at least one #reference
    if "#" not in prompt_text:
        return None

    # Extract directives from the wrapper prompt first so syntax like
    # "#split %model:..." can still flatten to #split while preserving
    # the user model override for nested workflow steps.
    from .directives import extract_prompt_directives

    prompt_text, wrapper_directives = extract_prompt_directives(prompt_text)
    prompt_text = prompt_text.strip()
    if not prompt_text.startswith("#"):
        return None

    prompts = get_all_prompts(project=project)
    logger.debug(
        "_flatten_anonymous_workflow: project=%r, cwd=%r, prompt=%r, "
        "prompt_keys_sample=%r, sase_prefix_keys=%r",
        project,
        os.getcwd(),
        prompt_text[:120],
        list(prompts.keys())[:20],
        [k for k in prompts if k.startswith("sase/")],
    )

    def _attach_wrapper_model(named: dict[str, str]) -> dict[str, str]:
        if not wrapper_directives.model:
            return named
        updated = dict(named)
        updated[_WORKFLOW_MODEL_OVERRIDE_ARG] = wrapper_directives.model
        return updated

    # ── Fast path: entire prompt is a single #name or #name(args) ──
    ref_text = prompt_text[1:]  # Strip leading #
    wf_name, positional_args, named_args = parse_workflow_reference(ref_text)

    if wf_name in prompts:
        referenced = prompts[wf_name]

        # Only flatten pure multi-step workflows (no prompt_part)
        # Workflows with prompt_part are handled by embedded workflow expansion
        if referenced.has_prompt_part():
            # Rename so workflow_state.json shows the real workflow name
            # instead of the anonymous "tmp_*" name (e.g., "resume" not
            # "tmp_260223_115114"). But don't rename if the args contain
            # additional # references, indicating a multi-reference prompt
            # (e.g., "#gh:sase #bd/next ...") rather than a single workflow
            # reference.
            has_extra_refs = any("#" in arg for arg in positional_args)
            if has_extra_refs:
                # Multi-reference prompt — fall through to slow path which
                # scans for a standalone workflow among the references.
                pass
            else:
                # Also check: the prompt may contain a standalone workflow
                # reference beyond the first (e.g., "#gh:sase #sase/pylimit_split").
                # The fast path only parsed the first reference, so scan the
                # full prompt text for a standalone workflow to flatten to.
                standalone = _find_standalone_workflow_ref(prompt_text, prompts)
                if standalone is not None:
                    ref_wf, pos, named = standalone
                    return ref_wf, pos, _attach_wrapper_model(named)
                logger.warning(
                    "_flatten_anonymous_workflow: fast-path has_prompt_part branch "
                    "returning None (workflow NOT flattened). prompt=%r, "
                    "first_ref=%r (has_prompt_part=True), standalone_scan=no match, "
                    "sase_prefix_keys=%r, all_keys_count=%d",
                    prompt_text[:200],
                    wf_name,
                    [k for k in prompts if k.startswith("sase/")],
                    len(prompts),
                )
                workflow.name = wf_name
                return None
        else:
            return referenced, positional_args, _attach_wrapper_model(named_args)

    # ── Slow path: multiple references, extract standalone workflow ──
    # The prompt may mix xprompt parts (e.g., #gh:sase) with a single
    # standalone workflow (no prompt_part). Scan for exactly one standalone
    # workflow reference and flatten to it.
    logger.debug(
        "_flatten_anonymous_workflow: fast path miss for %r, trying slow path",
        wf_name,
    )
    standalone = _find_standalone_workflow_ref(prompt_text, prompts)
    if standalone is None:
        logger.debug(
            "_flatten_anonymous_workflow: no standalone ref found, returning None"
        )
        return None
    ref_wf, pos, named = standalone
    logger.debug("_flatten_anonymous_workflow: flattened to %r", ref_wf.name)
    return ref_wf, pos, _attach_wrapper_model(named)


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
    from datetime import datetime

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
        "start_time": datetime.now().isoformat(),
        "pid": os.getpid(),
        "error": error_message,
        "is_anonymous": workflow_name.startswith("tmp_"),
    }
    if step_prompts:
        state_dict["step_prompts"] = step_prompts
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_dict, f, indent=2)


@dataclass
class WorkflowResult:
    """Result from executing a workflow.

    Attributes:
        output: JSON string of the last step's output.
        response_text: Raw response text from the last prompt step, if any.
        artifacts_dir: Path to the artifacts directory.
    """

    output: str
    response_text: str | None
    artifacts_dir: str


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
) -> WorkflowResult:
    """Execute a workflow and return its result.

    Args:
        name: The workflow name (can be a workflow or converted xprompt).
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
    from .workflow_models import WorkflowExecutionError
    from .workflow_output import WorkflowOutputHandler
    from .workflow_validator import validate_workflow

    if workflow_obj is not None:
        workflow = workflow_obj
    else:
        # Use unified loader to get both workflows and converted xprompts
        prompts = get_all_prompts(project=project)
        if name not in prompts:
            raise WorkflowExecutionError(f"Workflow '{name}' not found")
        workflow = prompts[name]

    # Create artifacts_dir early so we can write state on validation failure
    if artifacts_dir is None:
        from sase.core.paths import get_sase_tmpdir

        artifacts_dir = tempfile.mkdtemp(
            prefix=f"workflow-{name}-", dir=get_sase_tmpdir()
        )
    else:
        os.makedirs(artifacts_dir, exist_ok=True)

    # Handle simple xprompts: convert prompt_part to prompt step so they go
    # through WorkflowExecutor (producing workflow_state.json and markers)
    if workflow.is_simple_xprompt():
        from sase.xprompt.workflow_executor_utils import render_template
        from sase.xprompt.workflow_models import Workflow as WfModel

        # Build render context with positional args mapped to input names
        render_ctx: dict[str, Any] = dict(named_args)
        for i, value in enumerate(positional_args):
            if i < len(workflow.inputs):
                input_arg = workflow.inputs[i]
                if input_arg.name not in render_ctx:
                    render_ctx[input_arg.name] = value
        # Apply defaults for missing inputs
        for input_arg in workflow.inputs:
            if input_arg.name not in render_ctx and input_arg.default is not UNSET:
                render_ctx[input_arg.name] = input_arg.default

        content = workflow.get_prompt_part_content()
        rendered = render_template(content, render_ctx)
        workflow = WfModel(
            name=workflow.name,
            inputs=[],
            steps=[WorkflowStep(name="main", agent=rendered)],
            source_path=workflow.source_path,
            xprompts=workflow.xprompts,
        )

    # Flatten anonymous workflows that wrap a single multi-step workflow
    # reference (e.g., "sase run '#split(...)'" → execute split directly)
    if workflow.is_anonymous():
        flattened = _flatten_anonymous_workflow(workflow, project=project)
        if flattened is not None:
            flattened_workflow, flattened_positional_args, flattened_named_args = (
                flattened
            )
            workflow = flattened_workflow
            positional_args = flattened_positional_args
            # Preserve caller-provided context (e.g., cl_name/project_file/workspace_num)
            # while allowing explicit args parsed from #workflow(...) to override.
            named_args = {**named_args, **flattened_named_args}
        # Sync name — _flatten may rename the workflow even when not flattening
        # (e.g., prompt_part workflows like #resume_by_chat get named but not replaced)
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
    if _WORKFLOW_MODEL_OVERRIDE_ARG in named_args:
        inherited_model_override = str(named_args[_WORKFLOW_MODEL_OVERRIDE_ARG])
        named_args = {
            k: v for k, v in named_args.items() if k != _WORKFLOW_MODEL_OVERRIDE_ARG
        }

    # Build args dict from positional and named args
    args: dict[str, Any] = dict(named_args)

    # Map positional args to input names
    for i, value in enumerate(positional_args):
        if i < len(workflow.inputs):
            input_arg = workflow.inputs[i]
            if input_arg.name not in args:
                args[input_arg.name] = value

    # Apply defaults for missing args
    for input_arg in workflow.inputs:
        if input_arg.name not in args and input_arg.default is not UNSET:
            args[input_arg.name] = input_arg.default

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
    )

    success = executor.execute()

    if not success:
        raise WorkflowExecutionError(f"Workflow '{name}' was rejected or failed")

    # Extract output and response text
    output_str = ""
    response_text: str | None = None
    if executor.state.steps:
        last_step = executor.state.steps[-1]
        if last_step.output:
            output_str = json.dumps(last_step.output, indent=2)
            # Extract raw response text from _raw key if present
            if isinstance(last_step.output, dict) and "_raw" in last_step.output:
                response_text = last_step.output["_raw"]

    return WorkflowResult(
        output=output_str,
        response_text=response_text,
        artifacts_dir=artifacts_dir,
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
    from sase.xprompt.workflow_executor_utils import render_template

    workflows = get_all_workflows()
    if workflow_name not in workflows:
        raise WorkflowValidationError(f"Workflow '{workflow_name}' not found")

    workflow = workflows[workflow_name]

    # Build args dict from positional and named args
    args: dict[str, Any] = dict(named_args)

    # Map positional args to input names
    for i, value in enumerate(positional_args):
        if i < len(workflow.inputs):
            input_arg = workflow.inputs[i]
            if input_arg.name not in args:
                args[input_arg.name] = value

    # Apply defaults for missing args
    for input_arg in workflow.inputs:
        if input_arg.name not in args and input_arg.default is not UNSET:
            args[input_arg.name] = input_arg.default

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
        prompt_part_content = render_template(prompt_part_content, args)

    return prompt_part_content, pre_steps, post_steps


__all__ = [
    "WorkflowResult",
    "execute_workflow",
    "expand_workflow_for_embedding",
    "is_workflow_reference",
]

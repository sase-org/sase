"""VCS diff and embedded-output helpers for workflow prompt steps."""

import os
from typing import Any

from sase.xprompt.workflow_executor_steps_embedded_types import (
    EmbeddedWorkflowInfo,
    map_output_by_type,
)
from sase.xprompt.workflow_executor_types import output_types_from_step
from sase.xprompt.workflow_models import StepState, WorkflowState, WorkflowStep


def capture_vcs_diff() -> str | None:
    """Capture uncommitted changes as a VCS diff, including untracked files.

    Returns:
        The VCS diff output, or None if no changes or an error occurred.
    """
    try:
        from sase.vcs_provider import get_vcs_provider

        provider = get_vcs_provider(os.getcwd())
        _, diff_text = provider.diff_with_untracked(os.getcwd())
        return diff_text
    except Exception:
        return None


def _collect_embedded_step_outputs(
    embedded_workflows: list[EmbeddedWorkflowInfo],
) -> tuple[str | None, dict[str, str]]:
    """Collect diff_path and meta_* fields from embedded step outputs.

    Scans both pre-steps and post-steps for meta_* fields.
    diff_path extraction remains post-step only.
    """
    diff_path: str | None = None
    meta_fields: dict[str, str] = {}
    for info in embedded_workflows:
        # Collect meta_* from ALL pre-steps
        for step in info.pre_steps:
            step_output = info.context.get(step.name)
            if isinstance(step_output, dict):
                for k, v in step_output.items():
                    if k.startswith("meta_") and v:
                        meta_fields[k] = str(v)
        # Collect meta_* from ALL post-steps
        for step in info.post_steps:
            step_output = info.context.get(step.name)
            if isinstance(step_output, dict):
                for k, v in step_output.items():
                    if k.startswith("meta_") and v:
                        meta_fields[k] = str(v)
        # Extract path-type output from LAST post-step only
        # (first embedded workflow with post-steps wins)
        if info.post_steps and diff_path is None:
            last_step = info.post_steps[-1]
            step_output = info.context.get(last_step.name)
            if isinstance(step_output, dict) and last_step.output is not None:
                properties = last_step.output.schema.get("properties")
                if properties and isinstance(properties, dict):
                    for field_name, prop in properties.items():
                        if isinstance(prop, dict) and prop.get("type") == "path":
                            path_value = step_output.get(field_name)
                            if path_value:
                                diff_path = str(path_value)
                                break
    return diff_path, meta_fields


def resolve_embedded_path_fields(
    output: dict[str, Any],
    step: WorkflowStep,
    embedded_workflows: list[EmbeddedWorkflowInfo],
) -> None:
    """Populate missing path-type output fields from embedded workflow contexts.

    When a parent step declares path-type output fields (e.g., {desc_file: path}),
    the actual file paths may come from embedded workflow pre-steps. This resolves
    those paths before HITL review so file contents can be displayed.
    """
    parent_output_types = output_types_from_step(step)
    if not parent_output_types:
        return

    path_fields = {k for k, v in parent_output_types.items() if v == "path"}
    if not path_fields:
        return

    for info in embedded_workflows:
        for pre_step in info.pre_steps:
            if not pre_step.output:
                continue
            pre_step_output = info.context.get(pre_step.name)
            if not isinstance(pre_step_output, dict):
                continue
            # step.output is guaranteed non-None here because
            # output_types_from_step() returned a non-None dict above.
            assert step.output is not None
            mapped = map_output_by_type(step.output, pre_step.output, pre_step_output)
            if mapped is None:
                continue
            for field_name in path_fields:
                if field_name in mapped and field_name not in output:
                    output[field_name] = mapped[field_name]


def absolutize_path_outputs(output: dict[str, Any], step: WorkflowStep) -> None:
    """Make path-type output fields absolute for cross-process HITL."""
    step_output_types = output_types_from_step(step)
    if not step_output_types:
        return
    for field_name, field_type in step_output_types.items():
        if field_type == "path" and field_name in output:
            path_val = os.path.expanduser(str(output[field_name]))
            if not os.path.isabs(path_val):
                path_val = os.path.abspath(path_val)
            output[field_name] = path_val


def has_finally_post_steps(embedded_workflows: list[EmbeddedWorkflowInfo]) -> bool:
    """Return True when any embedded workflow has finally-marked post-steps."""
    return any(
        any(s.finally_ for s in info.post_steps)
        for info in embedded_workflows
        if info.post_steps
    )


def apply_embedded_outputs_to_parent(
    embedded_workflows: list[EmbeddedWorkflowInfo],
    *,
    step_name: str,
    step_state: StepState,
    context: dict[str, Any],
    state: WorkflowState,
    diff_path: str | None,
) -> tuple[str | None, bool]:
    """Merge embedded post-step outputs into the parent step state.

    Returns:
        ``(diff_path, resave_needed)``. ``diff_path`` may be replaced by an
        embedded path-type output so the TUI file panel shows the right file.
    """
    embedded_diff_path, embedded_meta = _collect_embedded_step_outputs(
        embedded_workflows
    )
    resave_needed = False
    if embedded_meta:
        if step_state.output is None:
            step_state.output = {}
        step_state.output.update(embedded_meta)
        context[step_name] = step_state.output
        state.context = dict(context)
        resave_needed = True
    # When embedded workflows appended post-steps, their path output
    # exclusively determines the file panel content for DONE entries
    has_appended_steps = any(info.post_steps for info in embedded_workflows)
    if has_appended_steps:
        diff_path = embedded_diff_path  # May be None → hides file panel
        if embedded_diff_path:
            if step_state.output is None:
                step_state.output = {}
            step_state.output["diff_path"] = embedded_diff_path
        resave_needed = True
    elif embedded_diff_path and not diff_path:
        # Embedded workflows without post-steps but with path (defensive)
        diff_path = embedded_diff_path
        if step_state.output is None:
            step_state.output = {}
        step_state.output["diff_path"] = embedded_diff_path
        resave_needed = True
    return diff_path, resave_needed

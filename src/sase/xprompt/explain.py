"""Dry-run / explain mode for xprompt workflows.

Shows the full execution plan without executing anything:
- Expanded xprompt references
- Resolved Jinja2 templates (where args allow)
- Step order, conditions, loops
- Output schemas and dependencies
"""

from __future__ import annotations

from typing import Any

from sase.xprompt.graph import (
    collect_all_step_names,
    control_annotations,
    extract_step_references,
    step_type,
)
from sase.xprompt.models import UNSET, InputArg
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _truncate(text: str, max_lines: int = 20) -> str:
    """Truncate multi-line text, showing a count of omitted lines."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    shown = "\n".join(lines[:max_lines])
    return f"{shown}\n  ... ({len(lines) - max_lines} more lines)"


def _indent(text: str, prefix: str = "    ") -> str:
    """Indent each line of text."""
    return "\n".join(prefix + line for line in text.splitlines())


def _format_input(inp: InputArg) -> str:
    """Format a single input argument for display."""
    parts = [f"{inp.name}: {inp.type.value}"]
    if inp.default is not UNSET:
        if inp.default is None:
            parts.append("(optional, default: null)")
        else:
            parts.append(f"(default: {inp.default!r})")
    else:
        parts.append("(required)")
    return " ".join(parts)


def _format_output_schema(step: WorkflowStep) -> str | None:
    """Format the output spec for a step."""
    if step.output is None:
        return None
    spec = step.output
    if spec.schema and "properties" in spec.schema:
        fields = []
        for name, prop in spec.schema["properties"].items():
            ftype = prop.get("type", "any")
            fields.append(f"{name}: {ftype}")
        return "{" + ", ".join(fields) + "}"
    return spec.type


def _render_step_body(step: WorkflowStep, context: dict[str, Any]) -> str | None:
    """Try to render the step's template with available context.

    Returns the rendered text, or the raw template if rendering fails
    (e.g. due to missing variables that would only exist at runtime).
    """
    from jinja2 import TemplateError

    from sase.xprompt.workflow_executor_utils import create_jinja_env

    raw = step.agent or step.bash or step.python or step.prompt_part
    if raw is None:
        return None

    env = create_jinja_env()
    try:
        template = env.from_string(raw)
        return template.render(context)
    except (TemplateError, TypeError):
        return raw


def _format_step(
    step: WorkflowStep,
    index: int,
    total: int,
    all_names: set[str],
    context: dict[str, Any],
) -> list[str]:
    """Format a single step for the explain output."""
    lines: list[str] = []
    stype = step_type(step)
    flow = control_annotations(step)

    # Step header
    header = f"Step {index}/{total}: {step.name}  [{stype}]"
    if flow:
        header += f"  {flow}"
    if step.hitl:
        header += "  [hitl]"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    # Condition
    if step.condition:
        lines.append(f"  if: {step.condition}")

    # Loop config
    if step.for_loop:
        for var, expr in step.for_loop.items():
            lines.append(f"  for {var} in: {expr}")
        if step.join:
            lines.append(f"  join: {step.join}")

    if step.repeat_config:
        lines.append(f"  repeat until: {step.repeat_config.condition}")
        lines.append(f"  max iterations: {step.repeat_config.max_iterations}")

    if step.while_config:
        lines.append(f"  while: {step.while_config.condition}")
        lines.append(f"  max iterations: {step.while_config.max_iterations}")

    # Parallel sub-steps
    if step.parallel_config:
        lines.append(f"  parallel (fail_fast={step.parallel_config.fail_fast}):")
        for sub in step.parallel_config.steps:
            sub_type = step_type(sub)
            lines.append(f"    - {sub.name} [{sub_type}]")

    # Step body (rendered or raw template)
    body = _render_step_body(step, context)
    if body is not None:
        label = (
            "command"
            if stype == "bash"
            else ("code" if stype == "python" else "prompt")
        )
        lines.append(f"  {label}:")
        lines.append(_indent(_truncate(body.strip()), "    "))

    # Output schema
    schema_str = _format_output_schema(step)
    if schema_str:
        lines.append(f"  output: {schema_str}")

    # Dependencies
    refs = extract_step_references(step, all_names)
    if refs:
        lines.append(f"  depends on: {', '.join(sorted(refs))}")

    return lines


def explain_workflow(
    workflow: Workflow,
    positional_args: list[str] | None = None,
    named_args: dict[str, str] | None = None,
) -> str:
    """Generate a dry-run explanation of a workflow.

    Shows the full execution plan: inputs, step order, resolved templates,
    conditions, loops, output schemas, and dependencies — without executing.

    Args:
        workflow: The workflow to explain.
        positional_args: Optional positional arguments.
        named_args: Optional named arguments.

    Returns:
        Human-readable explanation string.
    """
    positional_args = positional_args or []
    named_args = named_args or {}

    out: list[str] = []

    # Header
    out.append(f"Workflow: {workflow.name}")
    if workflow.source_path:
        out.append(f"Source: {workflow.source_path}")
    out.append(f"Steps: {len(workflow.steps)}")
    if workflow.wraps_all:
        out.append("Mode: wraps_all (workspace setup/teardown)")

    # Inputs
    explicit_inputs = [
        i for i in workflow.inputs if not getattr(i, "is_step_input", False)
    ]
    if explicit_inputs:
        out.append("")
        out.append("Inputs:")
        for inp in explicit_inputs:
            out.append(f"  - {_format_input(inp)}")

    # Build context from provided args (for template rendering)
    context: dict[str, Any] = dict(named_args)
    for i, value in enumerate(positional_args):
        if i < len(workflow.inputs):
            inp = workflow.inputs[i]
            if inp.name not in context:
                context[inp.name] = value
    # Apply defaults
    for inp in workflow.inputs:
        if inp.name not in context and inp.default is not UNSET:
            if inp.default is not None:
                context[inp.name] = inp.default

    # Show resolved args
    if context:
        out.append("")
        out.append("Resolved args:")
        for k, v in context.items():
            # Skip step inputs
            inp_def = workflow.get_input_by_name(k)
            if inp_def and getattr(inp_def, "is_step_input", False):
                continue
            out.append(f"  {k} = {v!r}")

    # Local xprompts
    if workflow.xprompts:
        out.append("")
        out.append(f"Local xprompts: {', '.join(sorted(workflow.xprompts))}")

    # Execution plan
    out.append("")
    out.append("Execution plan:")
    out.append("=" * 60)

    all_names = collect_all_step_names(workflow.steps)
    total = len(workflow.steps)

    for i, step in enumerate(workflow.steps, 1):
        out.append("")
        out.extend(_format_step(step, i, total, all_names, context))

    return "\n".join(out)

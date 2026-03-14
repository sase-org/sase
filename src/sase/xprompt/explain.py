"""Dry-run / explain mode for xprompt workflows.

Shows the full execution plan without executing anything:
- Expanded xprompt references
- Resolved Jinja2 templates (where args allow)
- Step order, conditions, loops
- Output schemas and dependencies
"""

from __future__ import annotations

from typing import Any

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from sase.xprompt.graph import (
    collect_all_step_names,
    control_annotations,
    extract_step_references,
    step_type,
)
from sase.xprompt.models import UNSET, InputArg
from sase.xprompt.workflow_models import Workflow, WorkflowStep

# Step type → color
_TYPE_COLORS: dict[str, str] = {
    "bash": "green",
    "python": "yellow",
    "agent": "cyan",
    "prompt_part": "magenta",
    "parallel": "blue",
    "unknown": "white",
}

# Syntax highlighting lexer per step type
_SYNTAX_LEXER: dict[str, str] = {
    "bash": "bash",
    "python": "python",
    "agent": "markdown",
    "prompt_part": "markdown",
}


def _truncate(text: str, max_lines: int = 20) -> str:
    """Truncate multi-line text, showing a count of omitted lines."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    shown = "\n".join(lines[:max_lines])
    return f"{shown}\n  ... ({len(lines) - max_lines} more lines)"


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
    """Try to render the step's template with available context."""
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


def _type_badge(stype: str) -> Text:
    """Create a colored badge like [bash] for the step type."""
    color = _TYPE_COLORS.get(stype, "white")
    return Text(f"[{stype}]", style=f"bold {color}")


def _render_step(
    step: WorkflowStep,
    index: int,
    total: int,
    all_names: set[str],
    context: dict[str, Any],
) -> Panel:
    """Render a single step as a Rich Panel."""
    stype = step_type(step)
    flow = control_annotations(step)
    color = _TYPE_COLORS.get(stype, "white")

    # --- Build title line ---
    title = Text()
    title.append(f"Step {index}/{total}", style="bold white")
    title.append("  ", style="default")
    title.append(step.name, style=f"bold {color}")
    title.append("  ", style="default")
    title.append_text(_type_badge(stype))
    if flow:
        title.append(f"  {flow}", style="bold yellow")
    if step.hitl:
        title.append("  [hitl]", style="bold red")

    # --- Body renderables ---
    parts: list[RenderableType] = []

    # Condition
    if step.condition:
        line = Text()
        line.append("if: ", style="bold yellow")
        line.append(step.condition, style="italic")
        parts.append(line)

    # Loop config
    if step.for_loop:
        for var, expr in step.for_loop.items():
            line = Text()
            line.append("for ", style="bold yellow")
            line.append(var, style="bold cyan")
            line.append(" in: ", style="bold yellow")
            line.append(expr, style="italic")
            parts.append(line)
        if step.join:
            line = Text()
            line.append("join: ", style="bold yellow")
            line.append(step.join, style="italic")
            parts.append(line)

    if step.repeat_config:
        line = Text()
        line.append("repeat until: ", style="bold yellow")
        line.append(step.repeat_config.condition, style="italic")
        parts.append(line)
        parts.append(
            Text(f"max iterations: {step.repeat_config.max_iterations}", style="dim")
        )

    if step.while_config:
        line = Text()
        line.append("while: ", style="bold yellow")
        line.append(step.while_config.condition, style="italic")
        parts.append(line)
        parts.append(
            Text(f"max iterations: {step.while_config.max_iterations}", style="dim")
        )

    # Parallel sub-steps
    if step.parallel_config:
        line = Text()
        line.append("parallel ", style="bold blue")
        line.append(f"(fail_fast={step.parallel_config.fail_fast})", style="dim")
        parts.append(line)
        for sub in step.parallel_config.steps:
            sub_type = step_type(sub)
            sub_line = Text("  - ", style="dim")
            sub_line.append(sub.name, style="bold")
            sub_line.append(" ")
            sub_line.append_text(_type_badge(sub_type))
            parts.append(sub_line)

    # Step body with syntax highlighting
    body = _render_step_body(step, context)
    if body is not None:
        label = (
            "command"
            if stype == "bash"
            else ("code" if stype == "python" else "prompt")
        )
        label_text = Text(f"{label}:", style="bold white")
        parts.append(label_text)
        lexer = _SYNTAX_LEXER.get(stype, "text")
        parts.append(
            Syntax(
                _truncate(body.strip()),
                lexer,
                theme="monokai",
                word_wrap=True,
                padding=(0, 2),
            )
        )

    # Output schema
    schema_str = _format_output_schema(step)
    if schema_str:
        line = Text()
        line.append("output: ", style="bold green")
        line.append(schema_str, style="green")
        parts.append(line)

    # Dependencies
    refs = extract_step_references(step, all_names)
    if refs:
        line = Text()
        line.append("depends on: ", style="bold blue")
        line.append(", ".join(sorted(refs)), style="blue")
        parts.append(line)

    return Panel(
        Group(*parts),
        title=title,
        title_align="left",
        border_style=color,
        padding=(0, 1),
    )


def _build_inputs_table(inputs: list[InputArg]) -> Table:
    """Build a Rich Table for workflow inputs."""
    table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        pad_edge=False,
        box=None,
    )
    table.add_column("Name", style="bold cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Required", style="white")
    table.add_column("Default", style="dim")

    for inp in inputs:
        required = "yes" if inp.default is UNSET else ""
        if inp.default is UNSET:
            default_val = ""
        elif inp.default is None:
            default_val = "null"
        else:
            default_val = repr(inp.default)
        table.add_row(inp.name, inp.type.value, required, default_val)

    return table


def explain_workflow(
    workflow: Workflow,
    positional_args: list[str] | None = None,
    named_args: dict[str, str] | None = None,
    console: Console | None = None,
) -> None:
    """Print a rich explanation of a workflow's execution plan.

    Shows the full execution plan: inputs, step order, resolved templates,
    conditions, loops, output schemas, and dependencies — without executing.
    """
    console = console or Console()
    positional_args = positional_args or []
    named_args = named_args or {}

    # --- Header panel ---
    header_parts: list[RenderableType] = []

    source_text = Text()
    source_text.append("Source: ", style="bold")
    source_text.append(workflow.source_path or "unknown", style="dim italic")
    header_parts.append(source_text)

    steps_text = Text()
    steps_text.append("Steps:  ", style="bold")
    steps_text.append(str(len(workflow.steps)), style="bold white")
    header_parts.append(steps_text)

    if workflow.wraps_all:
        mode_text = Text()
        mode_text.append("Mode:   ", style="bold")
        mode_text.append("wraps_all", style="bold magenta")
        mode_text.append(" (workspace setup/teardown)", style="dim")
        header_parts.append(mode_text)

    header_title = Text()
    header_title.append(workflow.name, style="bold cyan")

    console.print(
        Panel(
            Group(*header_parts),
            title=header_title,
            title_align="left",
            border_style="cyan",
            padding=(0, 1),
        )
    )

    # --- Inputs ---
    explicit_inputs = [
        i for i in workflow.inputs if not getattr(i, "is_step_input", False)
    ]
    if explicit_inputs:
        console.print()
        console.print(Text("Inputs", style="bold underline"))
        console.print(_build_inputs_table(explicit_inputs))

    # --- Build context from provided args ---
    context: dict[str, Any] = dict(named_args)
    for i, value in enumerate(positional_args):
        if i < len(workflow.inputs):
            inp = workflow.inputs[i]
            if inp.name not in context:
                context[inp.name] = value
    for inp in workflow.inputs:
        if inp.name not in context and inp.default is not UNSET:
            if inp.default is not None:
                context[inp.name] = inp.default

    # --- Resolved args ---
    resolved: dict[str, Any] = {}
    for k, v in context.items():
        inp_def = workflow.get_input_by_name(k)
        if inp_def and getattr(inp_def, "is_step_input", False):
            continue
        resolved[k] = v

    if resolved:
        console.print()
        console.print(Text("Resolved args", style="bold underline"))
        for k, v in resolved.items():
            line = Text()
            line.append(f"  {k}", style="bold cyan")
            line.append(" = ", style="dim")
            line.append(repr(v), style="white")
            console.print(line)

    # --- Local xprompts ---
    if workflow.xprompts:
        console.print()
        line = Text()
        line.append("Local xprompts: ", style="bold underline")
        line.append(", ".join(sorted(workflow.xprompts)), style="magenta")
        console.print(line)

    # --- Execution plan ---
    console.print()
    console.print(Rule("Execution Plan", style="bold white"))

    all_names = collect_all_step_names(workflow.steps)
    total = len(workflow.steps)

    for i, step in enumerate(workflow.steps, 1):
        console.print()
        console.print(
            Padding(
                _render_step(step, i, total, all_names, context),
                (0, 0),
            )
        )

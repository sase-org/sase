"""Preview and metadata formatting for the XPrompt browser pane."""

from __future__ import annotations

from rich.text import Text

from sase.xprompt.models import UNSET, InputArg
from sase.xprompt.workflow_step_display import workflow_step_type_label
from sase.xprompt.workflow_models import Workflow

from .xprompt_browser_helpers import BrowserItem


def create_preview_content(workflow: Workflow) -> str:
    """Create the preview markdown for a workflow or simple xprompt."""
    if workflow.is_simple_xprompt():
        return create_simple_preview(workflow)
    return create_workflow_preview(workflow)


def create_simple_preview(workflow: Workflow) -> str:
    """Create a preview for a simple xprompt."""
    content = workflow.get_prompt_part_content()
    inputs = [inp for inp in workflow.inputs if not inp.is_step_input]
    has_input_descriptions = any(inp.description for inp in inputs)
    if workflow.memory_type is not None:
        memory_lines: list[str] = [
            f"# Memory: {workflow.name}",
            "",
            f"memory type: {workflow.memory_type}",
            "",
        ]
        if workflow.description:
            memory_lines.extend([workflow.description, ""])
        if inputs:
            memory_lines.append("## Inputs")
            memory_lines.extend(_input_preview_lines(inputs))
            memory_lines.append("")
        memory_lines.extend(["## Content", content])
        return "\n".join(memory_lines)
    if not workflow.description and not has_input_descriptions:
        return content

    lines: list[str] = [f"# XPrompt: {workflow.name}", ""]
    if workflow.description:
        lines.extend([workflow.description, ""])
    if inputs:
        lines.append("## Inputs")
        lines.extend(_input_preview_lines(inputs))
        lines.append("")
    lines.extend(["## Content", content])
    return "\n".join(lines)


def create_workflow_preview(workflow: Workflow) -> str:
    """Create a preview string for a workflow."""
    lines: list[str] = [f"# Workflow: {workflow.name}", ""]
    if workflow.description:
        lines.extend([workflow.description, ""])
    inputs = [inp for inp in workflow.inputs if not inp.is_step_input]
    if inputs:
        lines.append("## Inputs")
        lines.extend(_input_preview_lines(inputs))
        lines.append("")
    lines.append("## Steps")
    for i, step in enumerate(workflow.steps, 1):
        step_type, step_label = workflow_step_type_label(step)
        lines.append(f"{i}. [{step_type}] {step.name}: {step_label}")
    return "\n".join(lines)


def create_meta_text(item: BrowserItem) -> Text:
    """Create the metadata block for a browser item."""
    workflow = item.workflow
    meta_text = Text()
    meta_text.append("── Source Info ──\n", style="bold dim")
    meta_text.append("Source: ", style="bold")
    meta_text.append(f"{item.display_path}\n")
    meta_text.append("Type: ", style="bold")
    meta_text.append(item.kind.replace("_", " "))
    if item.kind == "memory" and workflow.memory_type:
        meta_text.append(f" · {workflow.memory_type}")
    if item.item_type == "workflow":
        meta_text.append(f" ({len(workflow.steps)} steps)")
    else:
        meta_text.append(" (simple)")
    meta_text.append("\n")
    meta_text.append("Insertion: ", style="bold")
    meta_text.append(f"{item.insertion}\n")

    if workflow.description:
        meta_text.append("Description: ", style="bold")
        meta_text.append(workflow.description)
        meta_text.append("\n")

    if workflow.inputs:
        input_strs = [
            _input_meta_line(inp) for inp in workflow.inputs if not inp.is_step_input
        ]
        if input_strs:
            meta_text.append("Inputs:\n", style="bold")
            for input_str in input_strs:
                meta_text.append(f"  {input_str}\n")

    meta_text.append("Editable: ", style="bold")
    meta_text.append(
        "yes" if item.is_editable else "no",
        style="green" if item.is_editable else "red",
    )
    return meta_text


def _input_preview_lines(inputs: list[InputArg]) -> list[str]:
    lines: list[str] = []
    for inp in inputs:
        description_str = f" - {inp.description}" if inp.description else ""
        lines.append(
            f"- **{inp.name}**: {inp.type.value}{_default_suffix(inp)}{description_str}"
        )
    return lines


def _input_meta_line(inp: InputArg) -> str:
    description_str = f": {inp.description}" if inp.description else ""
    return f"{inp.name} ({inp.type.value}{_default_suffix(inp)}){description_str}"


def _default_suffix(inp: InputArg) -> str:
    if inp.default is UNSET:
        return ""
    if inp.default is None:
        return " (default: null)"
    return f" (default: {inp.default})"


__all__ = [
    "create_meta_text",
    "create_preview_content",
    "create_simple_preview",
    "create_workflow_preview",
]

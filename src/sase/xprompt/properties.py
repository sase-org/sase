"""Shared projection of an xprompt/workflow definition into display properties.

``sase xprompt show`` and the ACE preview reader both need to answer "what
does this xprompt take, and what else does it declare?" for one resolved
definition. This module is the single place that projection is computed, so
the two surfaces cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sase.xprompt._catalog_format import format_inputs
from sase.xprompt.cli_show_model import ShowInput, ShowLocalXPrompt, ShowStep
from sase.xprompt.models import (
    UNSET,
    InputArg,
    MemoryType,
    XPrompt,
    xprompt_to_workflow,
)
from sase.xprompt.segment_separators import xprompt_segment_count
from sase.xprompt.workflow_models import Workflow
from sase.xprompt.workflow_step_display import workflow_step_type_label


@dataclass(frozen=True, slots=True)
class XPromptProperties:
    """Display-ready properties of one resolved xprompt or workflow."""

    reference: str
    kind: str
    description: str | None
    input_signature: str | None
    inputs: list[ShowInput]
    local_xprompts: list[ShowLocalXPrompt]
    steps: list[ShowStep]
    tags: list[str]
    skill: bool | list[str] | None
    skill_name: str | None
    snippet: str | bool | None
    log_skill_use: bool | None
    memory_type: MemoryType | None
    segment_count: int
    project: str | None
    source_bucket: str | None
    definition_path: str | None

    @property
    def is_empty(self) -> bool:
        """Whether there is nothing worth rendering for this definition."""
        return not (
            self.description
            or self.inputs
            or self.local_xprompts
            or self.steps
            or self.tags
            or self.skill
            or self.snippet
            or self.memory_type
            or self.segment_count > 1
        )


def xprompt_properties(
    obj: XPrompt | Workflow,
    *,
    reference: str,
    kind: str,
    project: str | None = None,
    source_bucket: str | None = None,
    definition_path: str | None = None,
) -> XPromptProperties:
    """Project *obj* into the properties shared by show and preview surfaces."""
    xprompt = obj if isinstance(obj, XPrompt) else None
    workflow = xprompt_to_workflow(obj) if isinstance(obj, XPrompt) else obj

    body = workflow.get_prompt_part_content() if workflow.has_prompt_part() else None
    segment_count = (
        xprompt_segment_count(XPrompt(name=workflow.name, content=body))
        if body is not None
        else 0
    )

    return XPromptProperties(
        reference=reference,
        kind=kind,
        description=workflow.description,
        input_signature=format_inputs(workflow.inputs) or None,
        inputs=show_inputs(workflow.inputs),
        local_xprompts=show_local_xprompts(workflow.xprompts),
        steps=show_steps(workflow),
        tags=sorted(tag.value for tag in workflow.tags),
        skill=xprompt.skill if xprompt is not None else None,
        skill_name=xprompt.skill_name if xprompt is not None else None,
        snippet=xprompt.snippet if xprompt is not None else None,
        log_skill_use=xprompt.log_skill_use if xprompt is not None else None,
        memory_type=workflow.memory_type,
        segment_count=segment_count,
        project=project,
        source_bucket=source_bucket,
        definition_path=definition_path,
    )


def show_inputs(inputs: list[InputArg]) -> list[ShowInput]:
    """Project declared inputs into their display-ready row shape."""
    rows: list[ShowInput] = []
    for input_arg in inputs:
        if input_arg.is_step_input:
            continue
        rows.append(
            ShowInput(
                name=input_arg.name,
                type=input_arg.type.value,
                required=input_arg.default is UNSET,
                default_display=_default_display(input_arg.default),
                description=input_arg.description,
                repeatable=input_arg.repeatable,
                position=len(rows),
                choices=tuple(choice.value for choice in input_arg.choices),
            )
        )
    return rows


def _default_display(value: Any) -> str | None:
    if value is UNSET:
        return None
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def show_local_xprompts(
    local_xprompts: dict[str, XPrompt],
) -> list[ShowLocalXPrompt]:
    """Project local (prompt-scoped) xprompt definitions into display rows."""
    return [
        ShowLocalXPrompt(
            name=name,
            description=xprompt.description,
            input_signature=format_inputs(xprompt.inputs) or None,
            line_count=len(xprompt.content.splitlines()),
        )
        for name, xprompt in local_xprompts.items()
    ]


def show_steps(workflow: Workflow) -> list[ShowStep]:
    """Project a workflow's steps into display rows, or ``[]`` for a plain xprompt."""
    if workflow.is_simple_xprompt():
        return []
    rows: list[ShowStep] = []
    for index, step in enumerate(workflow.steps, start=1):
        step_type, label = workflow_step_type_label(step)
        rows.append(
            ShowStep(
                index=index,
                name=step.name,
                type=step_type,
                label=label,
                hidden=step.hidden,
                condition=step.condition,
                output_schema=(dict(step.output.schema) if step.output else None),
                body=step.agent or step.bash or step.python or step.prompt_part,
            )
        )
    return rows


def single_line_default(value: str) -> str:
    """Return *value*'s first line, appending an ellipsis if it continues."""
    lines = value.splitlines()
    if not lines:
        return ""
    return lines[0] + (" …" if len(lines) > 1 else "")


__all__ = [
    "XPromptProperties",
    "show_inputs",
    "show_local_xprompts",
    "show_steps",
    "single_line_default",
    "xprompt_properties",
]

"""Display and insertion helpers for xprompt references."""

from __future__ import annotations

from sase.xprompt.segment_separators import xprompt_content_has_segment_separators
from sase.xprompt.workflow_models import Workflow, WorkflowKind


def _workflow_uses_standalone_reference_marker(workflow: Workflow) -> bool:
    """Return True when the workflow-like entry should be inserted as ``#!``."""
    kind = workflow.prompt_kind()
    if kind is WorkflowKind.STANDALONE_WORKFLOW:
        return True
    return (
        kind is WorkflowKind.SIMPLE_XPROMPT
        and xprompt_content_has_segment_separators(workflow.get_prompt_part_content())
    )


def workflow_kind_value(workflow: Workflow) -> str:
    """Return the stable catalog kind for a workflow-like xprompt entry."""
    kind = workflow.prompt_kind()
    if kind is WorkflowKind.SIMPLE_XPROMPT:
        return "xprompt"
    return kind.value


def workflow_reference_prefix(workflow: Workflow) -> str:
    """Return the user-facing reference prefix for a workflow-like entry."""
    if _workflow_uses_standalone_reference_marker(workflow):
        return "#!"
    return "#"


def workflow_reference_insertion(name: str, workflow: Workflow) -> str:
    """Return the complete text inserted for an xprompt reference."""
    return f"{workflow_reference_prefix(workflow)}{name}"


def workflow_reference_suffix(name: str, workflow: Workflow) -> str:
    """Return the suffix inserted after an already-typed ``#`` trigger."""
    insertion = workflow_reference_insertion(name, workflow)
    return insertion[1:]

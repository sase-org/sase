"""Types and helpers for embedded workflow execution."""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sase.xprompt.models import OutputSpec
from sase.xprompt.workflow_models import Workflow, WorkflowStep

_logger = logging.getLogger(__name__)

# Matches content starting with a %xprompts_enabled:false marker.
# Used to detect when expanded content needs a preceding newline so the
# marker remains at line-start (required by disabled-region handling).
_DISABLED_REGION_START_RE = re.compile(r"[ \t]*%xprompts_enabled:false")

# Pattern to match workflow references in prompts (same as processor.py)
_WORKFLOW_REF_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"(?:(\()|:(`[^`]*`|[a-zA-Z0-9_.~/-]+)|(\+))?"  # Supports backtick-delimited colon args
)


@dataclass
class EmbeddedWorkflowInfo:
    """Information about an embedded workflow expanded from a prompt reference.

    Attributes:
        pre_steps: Steps executed before the prompt_part.
        post_steps: Steps executed after the main prompt completes.
        context: Isolated context for the embedded workflow (args + outputs).
        workflow_name: Name of the embedded workflow.
        nested_step_name: For parallel: which nested step this belongs to.
    """

    pre_steps: list[WorkflowStep]
    post_steps: list[WorkflowStep]
    context: dict[str, Any]
    workflow_name: str
    nested_step_name: str | None = None


@dataclass
class PendingEmbeddedWorkflow:
    """Collected match data for an embedded workflow reference between phases.

    Attributes:
        name: Workflow name (e.g. "git", "commit").
        workflow: The resolved Workflow object.
        match_start: Start position of the reference in the prompt.
        match_end: End position of the reference in the prompt (after args).
        args: Resolved args dict (with defaults applied).
        explicit_args: Args explicitly provided by the user (before defaults).
        embedded_context: Isolated context for the workflow (filled during execution).
        rendered_prompt_part: Rendered prompt_part content (filled during execution).
    """

    name: str
    workflow: Workflow
    match_start: int
    match_end: int
    args: dict[str, Any]
    explicit_args: dict[str, str]
    embedded_context: dict[str, Any] = field(default_factory=dict)
    rendered_prompt_part: str = ""


def _get_type_to_keys(spec: OutputSpec) -> dict[str, list[str]]:
    """Build a mapping from property type -> list of property names.

    Args:
        spec: The OutputSpec to extract type info from.

    Returns:
        Dict mapping type strings (e.g. "path") to lists of property names.
    """
    result: dict[str, list[str]] = {}
    for key, prop in spec.schema.get("properties", {}).items():
        prop_type = prop.get("type", "") if isinstance(prop, dict) else ""
        result.setdefault(prop_type, []).append(key)
    return result


def map_output_by_type(
    parent_spec: OutputSpec,
    embedded_spec: OutputSpec,
    embedded_output: dict[str, Any],
) -> dict[str, Any] | None:
    """Map embedded output values to parent output keys by matching property types.

    For each property type declared in the parent output spec, find the
    corresponding property in the embedded output spec with the same type
    and map its value to the parent key name.

    Args:
        parent_spec: The parent step's output specification.
        embedded_spec: The embedded post-step's output specification.
        embedded_output: The actual output dict from the embedded step.

    Returns:
        A new dict with parent key names mapped to embedded values, or None
        if the types don't match (e.g. parent has a type not present in embedded).
    """
    parent_types = _get_type_to_keys(parent_spec)
    embedded_types = _get_type_to_keys(embedded_spec)

    if not parent_types:
        return None

    mapped: dict[str, Any] = {}
    for prop_type, parent_keys in parent_types.items():
        embedded_keys = embedded_types.get(prop_type, [])
        if len(parent_keys) > len(embedded_keys):
            _logger.debug(
                "Type mismatch: parent has %d keys of type %r but embedded has %d",
                len(parent_keys),
                prop_type,
                len(embedded_keys),
            )
            return None
        # Map positionally: first parent key of type T gets first embedded key of type T
        for parent_key, embedded_key in zip(parent_keys, embedded_keys, strict=False):
            if embedded_key not in embedded_output:
                return None
            mapped[parent_key] = embedded_output[embedded_key]

    return mapped

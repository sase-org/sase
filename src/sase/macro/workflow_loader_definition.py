"""Parse individual YAML workflow definitions into workflow models."""

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.macro.loader_parsing import parse_macro_entries
from sase.macro.load_issues import record_load_issue
from sase.macro.models import UNSET, InputArg, InputType, MacroValidationError
from sase.macro.tags import MacroTag, parse_tags
from sase.macro.workflow_loader_parse import (
    parse_workflow_step as _parse_workflow_step,
    parse_workflow_inputs,
    validate_workflow_variables,
)
from sase.macro.workflow_loader_steps import resolve_step_imports
from sase.macro.workflow_models import (
    Workflow,
    WorkflowStep,
    WorkflowValidationError,
)

# legacy agent-family spelling: workflows authored with ``kind: agent_family``.
_REMOVED_LEGACY_AGENT_FAMILY_KIND_ERROR = (
    "kind: agent_family is no longer supported; attach agent session members "
    "manually with %i(suffix, session=parent). Agent-initiated agent session "
    "launches use LaunchApproval."
)


def namespace_workflow(project: str, workflow: Workflow) -> Workflow:
    """Return a copy of *workflow* named inside the project's namespace."""
    return Workflow(
        name=f"{project}/{workflow.name}",
        inputs=workflow.inputs,
        steps=workflow.steps,
        source_path=workflow.source_path,
        macros=workflow.macros,
        wraps_all=workflow.wraps_all,
        hidden=workflow.hidden,
        tags=workflow.tags,
        environment=workflow.environment,
        description=workflow.description,
        skill_name=workflow.skill_name,
        memory_type=workflow.memory_type,
        discovery_rank=workflow.discovery_rank,
    )


def load_workflow_from_mapping(
    name: str, data: dict[str, Any], source_path: str
) -> Workflow | None:
    """Load one workflow from parsed YAML data."""
    wraps_all = bool(data.get("wraps_all", False))
    hidden = bool(data.get("hidden", False))
    description_value = data.get("description")
    description = None if description_value is None else str(description_value)

    tags = parse_tags(data.get("tags"))
    if wraps_all and MacroTag.vcs not in tags:
        tags = tags | frozenset({MacroTag.vcs})
    if MacroTag.vcs in tags:
        wraps_all = True

    try:
        inputs = parse_workflow_inputs(data.get("input"))
    except MacroValidationError as exc:
        record_load_issue(source_path, exc, kind="workflow")
        return None

    from sase.legacy_xprompt_syntax import normalize_frontmatter_macros

    macros_data = normalize_frontmatter_macros(data, source=source_path)
    parsed_macros = parse_macro_entries(macros_data, source_path) if macros_data else {}

    environment_data = data.get("environment")
    environment: dict[str, str] = {}
    if isinstance(environment_data, dict):
        environment = {str(key): str(value) for key, value in environment_data.items()}

    steps_data = data.get("steps", [])
    if not isinstance(steps_data, list):
        record_load_issue(source_path, "steps must be a list", kind="workflow")
        return None

    steps: list[WorkflowStep] = []
    try:
        for step_index, step_data in enumerate(steps_data):
            if not isinstance(step_data, dict):
                continue
            if "use" in step_data:
                resolved = resolve_step_imports(
                    step_data,
                    workflow_source_path=source_path,
                )
                if resolved is None:
                    continue
                step_data = resolved
            steps.append(_parse_workflow_step(step_data, step_index))

        prompt_part_count = sum(1 for step in steps if step.is_prompt_part_step())
        if prompt_part_count > 1:
            raise WorkflowValidationError(
                f"Workflow '{name}' has {prompt_part_count} prompt_part steps, "
                "but at most one is allowed"
            )
    except WorkflowValidationError as exc:
        record_load_issue(source_path, exc, kind="workflow")
        return None

    if not steps:
        record_load_issue(
            source_path,
            "no valid workflow steps parsed",
            kind="workflow",
        )
        return None

    explicit_input_names = {input_arg.name for input_arg in inputs}
    for step in steps:
        if step.output is not None and step.name not in explicit_input_names:
            inputs.append(
                InputArg(
                    name=step.name,
                    type=InputType.LINE,
                    default=UNSET,
                    is_step_input=True,
                    output_schema=step.output,
                )
            )

    workflow = Workflow(
        name=str(name),
        inputs=inputs,
        steps=steps,
        source_path=source_path,
        macros=parsed_macros,
        wraps_all=wraps_all,
        hidden=hidden,
        tags=tags,
        environment=environment,
        description=description,
    )

    try:
        validate_workflow_variables(workflow)
    except WorkflowValidationError:
        # Runtime validation reports the richer context for unresolved variables.
        pass

    return workflow


def load_workflow_from_file(file_path: Path) -> Workflow | None:
    """Load a single workflow from a ``.yml`` or ``.yaml`` file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except (OSError, yaml.YAMLError) as exc:
        record_load_issue(file_path, exc, kind="workflow")
        return None

    if not isinstance(data, dict):
        record_load_issue(file_path, "top-level YAML is not a mapping", kind="workflow")
        return None
    if data.get("kind") == "agent_family":
        raise WorkflowValidationError(_REMOVED_LEGACY_AGENT_FAMILY_KIND_ERROR)

    return load_workflow_from_mapping(file_path.stem, data, str(file_path))

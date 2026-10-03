"""Compile-time validation for workflows.

Validates workflows before execution to catch errors early with clear messages.
"""

from sase.macro._parsing import preprocess_shorthand_syntax
from sase.macro.loader import get_all_macros
from sase.macro.workflow_models import Workflow, WorkflowValidationError
from sase.macro.workflow_validator_checks import (
    detect_unused_inputs,
    detect_unused_outputs,
    detect_unused_macro_inputs,
    detect_unused_macros,
    validate_cross_step_field_refs,
    validate_finally_steps,
    validate_prompt_part_steps,
    validate_macro_names,
)
from sase.macro.workflow_validator_extract import (
    collect_step_content,
    collect_used_variables,
    extract_macro_calls,
    validate_macro_call,
)


def validate_workflow(workflow: Workflow) -> None:
    """Validate a workflow before execution.

    Performs compile-time checks:
    - Validates macro names start with '_'
    - Detects unused inputs (defined but never referenced)
    - Validates macro calls (required args, named arg names, positional counts)
    - Validates prompt_part steps (at most one, no control flow, no output, no hitl)
    - Validates finally steps are at the end of the workflow

    Args:
        workflow: The workflow to validate.

    Raises:
        WorkflowValidationError: If validation fails.
    """
    errors: list[str] = []

    # Validate macro names early (before other macro checks)
    errors.extend(validate_macro_names(workflow))

    # Validate finally step ordering
    errors.extend(validate_finally_steps(workflow))

    macros = get_all_macros()
    macros.update(workflow.macros)  # workflow-local takes priority

    # Validate prompt_part steps
    prompt_part_errors = validate_prompt_part_steps(workflow)
    errors.extend(prompt_part_errors)

    # Check for unused inputs
    used_vars = collect_used_variables(workflow)
    unused_inputs = detect_unused_inputs(workflow, used_vars)
    if unused_inputs:
        errors.append(f"Unused inputs: {unused_inputs}")

    # Check for unused outputs
    unused_output_errors = detect_unused_outputs(workflow)
    errors.extend(unused_output_errors)

    # Check cross-step field references against output schemas
    errors.extend(validate_cross_step_field_refs(workflow))

    # Check for unused workflow-local macros
    errors.extend(detect_unused_macros(workflow, macros))

    # Check for unused workflow-local macro inputs
    errors.extend(detect_unused_macro_inputs(workflow))

    # Validate macro calls in each step
    for step in workflow.steps:
        for content in collect_step_content(step):
            # Preprocess shorthand syntax (#name: text -> #name([[text]]))
            preprocessed = preprocess_shorthand_syntax(content, set(macros.keys()))
            calls = extract_macro_calls(preprocessed)
            for call in calls:
                if call.name in macros:
                    macro_def = macros[call.name]
                    call_errors = validate_macro_call(call, macro_def, step.name)
                    errors.extend(call_errors)

    if errors:
        error_msg = f"Workflow '{workflow.name}' validation failed:\n"
        for error in errors:
            error_msg += f"  - {error}\n"
        raise WorkflowValidationError(error_msg.rstrip())

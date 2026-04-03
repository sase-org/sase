"""Individual validation checks for workflows.

Each function validates a specific aspect of workflow correctness
and returns a list of error messages (empty if valid).
"""

from sase.xprompt._parsing import preprocess_shorthand_syntax
from sase.xprompt.models import OutputSpec, XPrompt
from sase.xprompt.workflow_models import Workflow
from sase.xprompt.workflow_validator_extract import (
    collect_step_content,
    extract_template_refs,
    extract_xprompt_calls,
)


def detect_unused_inputs(workflow: Workflow, used_vars: set[str]) -> list[str]:
    """Find inputs that are defined but never used.

    Args:
        workflow: The workflow to check.
        used_vars: Set of variable names referenced in templates.

    Returns:
        List of unused input names.
    """
    unused: list[str] = []

    for inp in workflow.inputs:
        # Skip auto-generated step inputs
        if inp.is_step_input:
            continue
        if inp.name not in used_vars:
            unused.append(inp.name)

    return unused


def validate_prompt_part_steps(workflow: Workflow) -> list[str]:
    """Validate prompt_part steps in a workflow.

    Validates:
    - At most one prompt_part step per workflow
    - prompt_part steps cannot have loop control flow (for, repeat, while)
    - prompt_part steps cannot have output specification
    - prompt_part steps cannot have hitl: true

    Args:
        workflow: The workflow to validate.

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []
    prompt_part_count = 0

    for step in workflow.steps:
        if not step.is_prompt_part_step():
            continue

        prompt_part_count += 1

        # Validate no loop control flow (if: is allowed)
        if step.for_loop:
            errors.append(
                f"Step '{step.name}' with 'prompt_part' cannot have 'for' loop"
            )
        if step.repeat_config:
            errors.append(
                f"Step '{step.name}' with 'prompt_part' cannot have 'repeat' loop"
            )
        if step.while_config:
            errors.append(
                f"Step '{step.name}' with 'prompt_part' cannot have 'while' loop"
            )

        # Validate no output specification
        if step.output:
            errors.append(
                f"Step '{step.name}' with 'prompt_part' cannot have 'output' specification"
            )

        # Validate no HITL
        if step.hitl:
            errors.append(
                f"Step '{step.name}' with 'prompt_part' cannot have 'hitl: true'"
            )

    # Validate at most one prompt_part
    if prompt_part_count > 1:
        errors.append(
            f"Workflow has {prompt_part_count} prompt_part steps, "
            "but at most one is allowed"
        )

    return errors


def _mark_output_refs(content: str, output_usage: dict[str, bool]) -> None:
    """Scan content for template refs and mark matching output keys as used.

    Args:
        content: Template content string to scan.
        output_usage: Dict of output keys to used status (mutated in place).
    """
    for ref in extract_template_refs(content):
        parts = ref.split(".")

        if len(parts) == 1:
            # {{ step }} or {{ step | tojson }}
            if parts[0] in output_usage:
                output_usage[parts[0]] = True
        elif len(parts) == 2:
            # {{ step.field }} → marks "step"
            if parts[0] in output_usage:
                output_usage[parts[0]] = True
        else:
            # {{ parent.nested.field }} → marks "parent" and "parent.nested"
            if parts[0] in output_usage:
                output_usage[parts[0]] = True
            dotted = f"{parts[0]}.{parts[1]}"
            if dotted in output_usage:
                output_usage[dotted] = True


def detect_unused_outputs(workflow: Workflow) -> list[str]:
    """Find steps with output that are never referenced by other steps.

    The last step is exempt since its output may be consumed when the workflow
    is embedded (via _propagate_last_embedded_output).

    Args:
        workflow: The workflow to check.

    Returns:
        List of error messages for unused outputs.
    """
    output_usage: dict[str, bool] = {}
    output_fields: dict[str, str] = {}  # key → comma-separated quoted field names

    def _format_fields(output: OutputSpec) -> str:
        props = output.schema.get("properties", {})
        return ", ".join(f"'{f}'" for f in props)

    # Register all steps that have output
    for step in workflow.steps:
        if step.output:
            output_usage[step.name] = False
            output_fields[step.name] = _format_fields(step.output)
        if step.parallel_config:
            # Only track nested outputs when join is "object" or unset AND no for_loop
            join = step.join
            skip_nested = (
                join in ("array", "text", "lastOf") or step.for_loop is not None
            )
            if not skip_nested:
                for nested in step.parallel_config.steps:
                    if nested.output:
                        key = f"{step.name}.{nested.name}"
                        output_usage[key] = False
                        output_fields[key] = _format_fields(nested.output)

    # Scan all step content for references
    for step in workflow.steps:
        for content in collect_step_content(step):
            _mark_output_refs(content, output_usage)

    # Scan workflow-local xprompt content
    for xprompt in workflow.xprompts.values():
        _mark_output_refs(xprompt.content, output_usage)

    # Determine exempt steps (last step)
    exempt_keys: set[str] = set()
    if workflow.has_prompt_part():
        post_steps = workflow.get_post_prompt_steps()
        if post_steps:
            last_step = post_steps[-1]
        else:
            last_step = None
    else:
        last_step = workflow.steps[-1] if workflow.steps else None

    if last_step:
        exempt_keys.add(last_step.name)
        # If last step is parallel, exempt all nested steps too
        if last_step.parallel_config:
            for nested in last_step.parallel_config.steps:
                exempt_keys.add(f"{last_step.name}.{nested.name}")

    # Return errors for unused outputs that aren't exempt
    errors: list[str] = []
    for key, used in output_usage.items():
        if not used and key not in exempt_keys:
            fields = output_fields.get(key, "")
            field_desc = f" {fields}" if fields else ""
            errors.append(
                f"Step '{key}' has output{field_desc} but is never referenced"
            )

    return errors


def validate_cross_step_field_refs(workflow: Workflow) -> list[str]:
    """Validate that field references in templates match step output schemas.

    For each ``{{ step_name.field }}`` reference, verifies that *field* exists
    in *step_name*'s output schema properties.  Catches typos like
    ``{{ build.atrifact_path }}`` when the output defines ``artifact_path``.

    Args:
        workflow: The workflow to validate.

    Returns:
        List of error messages for invalid field references.
    """
    errors: list[str] = []

    # Build map: step_name → set of field names from output schema
    step_fields: dict[str, set[str]] = {}
    # Build map: "parent.nested" → set of field names for parallel substeps
    nested_fields: dict[str, set[str]] = {}
    # Track parallel steps → their substep names (for object-joined access)
    parallel_substep_names: dict[str, set[str]] = {}

    for step in workflow.steps:
        if step.output:
            # Field access works for steps without a for-loop, or with join=lastOf
            has_for = step.for_loop is not None
            if not has_for or step.join == "lastOf":
                props = step.output.schema.get("properties", {})
                step_fields[step.name] = set(props.keys())

        # Steps with artifact: stdout auto-inject _artifact into output
        if step.artifact:
            step_fields.setdefault(step.name, set()).add("_artifact")

        # Bash/python steps with hitl: true auto-inject 'approved' into output
        if step.hitl and (step.bash is not None or step.python is not None):
            step_fields.setdefault(step.name, set()).add("approved")

        if step.parallel_config:
            join = step.join
            skip_nested = (
                join in ("array", "text", "lastOf") or step.for_loop is not None
            )
            if not skip_nested:
                substeps: set[str] = set()
                for nested in step.parallel_config.steps:
                    substeps.add(nested.name)
                    if nested.output:
                        key = f"{step.name}.{nested.name}"
                        props = nested.output.schema.get("properties", {})
                        nested_fields[key] = set(props.keys())
                parallel_substep_names[step.name] = substeps

    def _check_refs(refs: list[str], source_label: str, for_vars: set[str]) -> None:
        for ref in refs:
            parts = ref.split(".")
            if len(parts) < 2:
                continue

            ref_name = parts[0]

            # Skip for-loop iteration variables
            if ref_name in for_vars:
                continue

            # Case 1: {{ step.field }} for a step with output schema
            if ref_name in step_fields:
                field = parts[1]
                known = step_fields[ref_name]
                if field not in known:
                    available = sorted(known)
                    errors.append(
                        f"{source_label}: references '{ref_name}.{field}' "
                        f"but '{ref_name}' output has no field '{field}'. "
                        f"Available: {available}"
                    )

            # Case 2: {{ parallel.nested.field }} for object-joined parallel
            elif ref_name in parallel_substep_names and len(parts) >= 3:
                nested_name = parts[1]
                field = parts[2]
                key = f"{ref_name}.{nested_name}"
                if key in nested_fields:
                    known = nested_fields[key]
                    if field not in known:
                        available = sorted(known)
                        errors.append(
                            f"{source_label}: references "
                            f"'{ref_name}.{nested_name}.{field}' "
                            f"but '{key}' output has no field '{field}'. "
                            f"Available: {available}"
                        )

    # Scan all step content
    for step in workflow.steps:
        for_vars = set(step.for_loop.keys()) if step.for_loop else set()
        label = f"Step '{step.name}'"

        for content in collect_step_content(step):
            _check_refs(extract_template_refs(content), label, for_vars)

    # Scan workflow-local xprompt content
    for xp_name, xp in workflow.xprompts.items():
        _check_refs(
            extract_template_refs(xp.content),
            f"Xprompt '{xp_name}'",
            set(),
        )

    return errors


def detect_unused_xprompts(
    workflow: Workflow, xprompts: dict[str, XPrompt]
) -> list[str]:
    """Find workflow-local xprompts that are never referenced.

    Scans step content and other workflow-local xprompt content for #name
    references. Any workflow-local xprompt not referenced anywhere is reported.

    Args:
        workflow: The workflow to check.
        xprompts: Merged xprompt dict (global + workflow-local).

    Returns:
        List of error messages for unused workflow-local xprompts.
    """
    if not workflow.xprompts:
        return []

    xprompt_usage: dict[str, bool] = dict.fromkeys(workflow.xprompts, False)
    xprompt_names = set(xprompts.keys())

    # Scan step content
    for step in workflow.steps:
        for content in collect_step_content(step):
            preprocessed = preprocess_shorthand_syntax(content, xprompt_names)
            for call in extract_xprompt_calls(preprocessed):
                if call.name in xprompt_usage:
                    xprompt_usage[call.name] = True

    # Scan other workflow-local xprompt content (xprompts can reference each other)
    for xp in workflow.xprompts.values():
        preprocessed = preprocess_shorthand_syntax(xp.content, xprompt_names)
        for call in extract_xprompt_calls(preprocessed):
            if call.name in xprompt_usage:
                xprompt_usage[call.name] = True

    errors: list[str] = []
    for name, used in xprompt_usage.items():
        if not used:
            errors.append(
                f"Workflow-local xprompt '{name}' is defined but never referenced"
            )
    return errors


def detect_unused_xprompt_inputs(workflow: Workflow) -> list[str]:
    """Find inputs on workflow-local xprompts that are never used in content.

    For each workflow-local xprompt that has inputs, checks whether each input
    name appears as a {{ variable }} reference in the xprompt's content.

    Args:
        workflow: The workflow to check.

    Returns:
        List of error messages for unused xprompt inputs.
    """
    errors: list[str] = []

    for name, xp in workflow.xprompts.items():
        if not xp.inputs:
            continue

        # Collect variable names used in this xprompt's content
        used_vars: set[str] = set()
        for ref in extract_template_refs(xp.content):
            used_vars.add(ref.split(".")[0])

        for inp in xp.inputs:
            if inp.name not in used_vars:
                errors.append(
                    f"Xprompt '{name}' input '{inp.name}' "
                    f"is defined but never referenced in its content"
                )

    return errors


def validate_xprompt_names(workflow: Workflow) -> list[str]:
    """Validate that all workflow-local xprompt names start with '_'.

    Args:
        workflow: The workflow to check.

    Returns:
        List of error messages for invalid xprompt names.
    """
    errors: list[str] = []
    for name in workflow.xprompts:
        if not name.startswith("_"):
            errors.append(
                f"Workflow-local xprompt '{name}' must start with '_' (e.g. '_{name}')"
            )
    return errors


def validate_finally_steps(workflow: Workflow) -> list[str]:
    """Validate that finally steps are correctly positioned.

    All ``finally: true`` steps must come after all non-finally steps.
    This ensures a clean separation between the main workflow body and
    cleanup/teardown steps.

    Args:
        workflow: The workflow to check.

    Returns:
        List of error messages (empty if valid).
    """
    errors: list[str] = []
    seen_finally = False
    for step in workflow.steps:
        if step.finally_:
            seen_finally = True
        elif seen_finally:
            errors.append(
                f"Step '{step.name}' is a non-finally step after finally step(s). "
                "All 'finally: true' steps must be at the end of the workflow"
            )
    return errors

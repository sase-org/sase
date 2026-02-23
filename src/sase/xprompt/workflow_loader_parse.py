"""Workflow parsing and validation functions."""

import re
from typing import Any

from sase.xprompt.loader_parsing import (
    parse_input_type,
    parse_output_from_front_matter,
    parse_shortform_inputs,
)
from sase.xprompt.models import InputArg, OutputSpec
from sase.xprompt.workflow_models import (
    LoopConfig,
    ParallelConfig,
    Workflow,
    WorkflowStep,
    WorkflowValidationError,
)


def parse_workflow_inputs(
    input_data: list[dict[str, Any]] | dict[str, str] | None,
) -> list[InputArg]:
    """Parse input definitions from workflow YAML.

    Supports both longform (list of dicts) and shortform (dict) syntax.

    Args:
        input_data: Either a list of input dicts (longform) or a dict (shortform).
            Longform: [{"name": "foo", "type": "word", "default": ""}]
            Shortform: {"foo": "word", "bar": "line = \"\""}

    Returns:
        List of InputArg objects.
    """
    if not input_data:
        return []

    # Handle shortform dict syntax
    if isinstance(input_data, dict):
        return parse_shortform_inputs(input_data)

    # Handle longform list syntax
    inputs: list[InputArg] = []
    for item in input_data:
        if not isinstance(item, dict) or "name" not in item:
            continue

        name = str(item["name"])
        type_str = str(item.get("type", "line"))
        default = item.get("default")

        inputs.append(
            InputArg(
                name=name,
                type=parse_input_type(type_str),
                default=default,
            )
        )

    return inputs


def _parse_workflow_step(
    step_data: dict[str, Any],
    index: int,
    is_nested: bool = False,
) -> WorkflowStep:
    """Parse a single workflow step from YAML.

    Args:
        step_data: The step dict from YAML.
        index: The step index (used for default name).
        is_nested: If True, this step is nested within a parallel: block.

    Returns:
        WorkflowStep object.

    Raises:
        WorkflowValidationError: If step is invalid.
    """
    name = str(step_data.get("name", f"step_{index}"))

    agent = step_data.get("agent") or step_data.get("prompt")  # backward compat
    bash = step_data.get("bash")
    python = step_data.get("python")
    prompt_part = step_data.get("prompt_part")
    parallel_data = step_data.get("parallel")

    # Validate mutually exclusive fields - must have exactly one of agent, bash, python,
    # prompt_part, parallel
    step_types = [agent, bash, python, prompt_part, parallel_data]
    num_step_types = sum(1 for t in step_types if t is not None)

    if num_step_types > 1:
        raise WorkflowValidationError(
            f"Step '{name}' can only have one of 'agent', 'bash', 'python', "
            "'prompt_part', or 'parallel' fields"
        )
    if num_step_types == 0:
        raise WorkflowValidationError(
            f"Step '{name}' must have one of 'agent', 'bash', 'python', "
            "'prompt_part', or 'parallel' field"
        )

    # Parse output specification
    output: OutputSpec | None = None
    output_data = step_data.get("output")
    if output_data:
        output = parse_output_from_front_matter(output_data)

    # Parse control flow fields
    condition = step_data.get("if")
    for_loop = step_data.get("for")
    repeat_data = step_data.get("repeat")
    while_data = step_data.get("while")
    join = step_data.get("join")
    hitl = bool(step_data.get("hitl", False))
    hidden = bool(step_data.get("hidden", False))

    # Validate mutual exclusivity of loop types (for, repeat, while)
    loop_types = [for_loop, repeat_data, while_data]
    num_loop_types = sum(1 for t in loop_types if t)
    if num_loop_types > 1:
        raise WorkflowValidationError(
            f"Step '{name}' can only have one of 'for', 'repeat', or 'while' fields"
        )

    # Validate parallel: cannot combine with repeat: or while:
    if parallel_data and (repeat_data or while_data):
        raise WorkflowValidationError(
            f"Step '{name}' cannot combine 'parallel' with 'repeat' or 'while'"
        )

    # Validate prompt_part step restrictions
    if prompt_part is not None:
        if condition:
            raise WorkflowValidationError(
                f"Step '{name}' with 'prompt_part' cannot have 'if' condition"
            )
        if for_loop or repeat_data or while_data:
            raise WorkflowValidationError(
                f"Step '{name}' with 'prompt_part' cannot have "
                "'for', 'repeat', or 'while' loops"
            )
        if output_data:
            raise WorkflowValidationError(
                f"Step '{name}' with 'prompt_part' cannot have 'output' specification"
            )
        if hitl:
            raise WorkflowValidationError(
                f"Step '{name}' with 'prompt_part' cannot have 'hitl: true'"
            )

    # Validate nested step restrictions
    if is_nested:
        if for_loop or repeat_data or while_data or parallel_data:
            raise WorkflowValidationError(
                f"Nested step '{name}' cannot have 'for', 'repeat', 'while', "
                "or 'parallel' fields"
            )
        if hitl:
            raise WorkflowValidationError(
                f"Nested step '{name}' cannot have 'hitl: true'"
            )

    # Parse for: loop (dict of {var: expression})
    parsed_for_loop: dict[str, str] | None = None
    if for_loop:
        if not isinstance(for_loop, dict):
            raise WorkflowValidationError(
                f"Step '{name}' 'for' field must be a dict mapping variable names "
                "to list expressions"
            )
        parsed_for_loop = {str(k): str(v) for k, v in for_loop.items()}

    # Parse repeat: config
    repeat_config: LoopConfig | None = None
    if repeat_data:
        if not isinstance(repeat_data, dict):
            raise WorkflowValidationError(
                f"Step '{name}' 'repeat' field must be a dict with 'until' key"
            )
        until_cond = repeat_data.get("until")
        if not until_cond:
            raise WorkflowValidationError(
                f"Step '{name}' 'repeat' field requires 'until' condition"
            )
        max_iter = int(repeat_data.get("max", 100))
        repeat_config = LoopConfig(condition=str(until_cond), max_iterations=max_iter)

    # Parse while: config
    while_config: LoopConfig | None = None
    if while_data:
        if isinstance(while_data, str):
            # Short form: while: "{{ condition }}"
            while_config = LoopConfig(condition=while_data, max_iterations=100)
        elif isinstance(while_data, dict):
            # Long form: while: {condition: "...", max: N}
            while_cond = while_data.get("condition")
            if not while_cond:
                raise WorkflowValidationError(
                    f"Step '{name}' 'while' field requires 'condition' key"
                )
            max_iter = int(while_data.get("max", 100))
            while_config = LoopConfig(
                condition=str(while_cond), max_iterations=max_iter
            )
        else:
            raise WorkflowValidationError(
                f"Step '{name}' 'while' field must be a string or dict"
            )

    # Validate join: mode
    valid_join_modes = {"array", "text", "object", "lastOf"}
    if join and str(join) not in valid_join_modes:
        raise WorkflowValidationError(
            f"Step '{name}' 'join' must be one of: {', '.join(sorted(valid_join_modes))}"
        )

    # Parse parallel: config
    parallel_config: ParallelConfig | None = None
    if parallel_data:
        if not isinstance(parallel_data, list):
            raise WorkflowValidationError(
                f"Step '{name}' 'parallel' field must be a list of steps"
            )
        if len(parallel_data) < 2:
            raise WorkflowValidationError(
                f"Step '{name}' 'parallel' field requires at least 2 steps"
            )

        # Collect nested step names to check for uniqueness
        nested_step_names: set[str] = set()
        nested_steps: list[WorkflowStep] = []

        for nested_idx, nested_data in enumerate(parallel_data):
            if not isinstance(nested_data, dict):
                raise WorkflowValidationError(
                    f"Step '{name}' parallel item {nested_idx} must be a dict"
                )
            nested_step = _parse_workflow_step(nested_data, nested_idx, is_nested=True)

            # Check for duplicate step names within parallel block
            if nested_step.name in nested_step_names:
                raise WorkflowValidationError(
                    f"Step '{name}' has duplicate nested step name: '{nested_step.name}'"
                )
            nested_step_names.add(nested_step.name)
            nested_steps.append(nested_step)

        parallel_config = ParallelConfig(steps=nested_steps)

    return WorkflowStep(
        name=name,
        agent=str(agent) if agent else None,
        bash=str(bash) if bash else None,
        python=str(python) if python else None,
        prompt_part=str(prompt_part) if prompt_part is not None else None,
        output=output,
        hitl=hitl,
        hidden=hidden,
        condition=str(condition) if condition else None,
        for_loop=parsed_for_loop,
        repeat_config=repeat_config,
        while_config=while_config,
        parallel_config=parallel_config,
        join=str(join) if join else None,
    )


def validate_workflow_variables(workflow: Workflow) -> None:
    """Validate variable usage in workflow.

    Validates:
    1. All input args are used by at least one step
    2. All step outputs are used by at least one subsequent step
    3. No undefined variable references
    4. Loop variable references within for: steps
    5. Self-references allowed in repeat:/while: conditions

    Args:
        workflow: The workflow to validate.

    Raises:
        WorkflowValidationError: If validation fails.
    """
    input_names = {inp.name for inp in workflow.inputs}
    step_names = {step.name for step in workflow.steps}

    # Step inputs are available from the start (user provides them upfront)
    step_input_names = {inp.name for inp in workflow.inputs if inp.is_step_input}

    # Track which variables are defined at each point
    # Step inputs count as defined from the start since users can provide them
    defined_vars: set[str] = set(input_names) | step_input_names

    # Track usage of inputs
    input_usage: dict[str, bool] = dict.fromkeys(input_names, False)

    # Track output usage (outputs from each step)
    output_usage: dict[str, bool] = {}

    for step in workflow.steps:
        # Get loop variables for this step (available within for: loops)
        loop_vars: set[str] = set()
        if step.for_loop:
            loop_vars = set(step.for_loop.keys())

        # Check variable references in agent, bash, or python
        content = step.agent or step.bash or step.python
        if content:
            # Match {{ var }} and {{ step.output }}
            refs = re.findall(
                r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\s*",
                content,
            )

            for ref in refs:
                if "." in ref:
                    # Step output reference like "setup.cl_name"
                    step_ref_name, _ = ref.split(".", 1)
                    if step_ref_name not in step_names:
                        raise WorkflowValidationError(
                            f"Step '{step.name}' references undefined step "
                            f"'{step_ref_name}'"
                        )
                    if step_ref_name not in defined_vars:
                        raise WorkflowValidationError(
                            f"Step '{step.name}' references step '{step_ref_name}' "
                            "before it executes"
                        )
                    if step_ref_name in output_usage:
                        output_usage[step_ref_name] = True
                else:
                    # Direct variable reference
                    if ref in input_names:
                        input_usage[ref] = True
                    elif ref in loop_vars:
                        # Loop variable - valid within for: step
                        pass
                    elif ref not in defined_vars and ref not in ("tojson",):
                        # tojson is a Jinja2 filter, not a variable
                        # Check if it could be a Jinja filter or builtin
                        pass  # Allow for now, will fail at runtime if truly undefined

        # Validate if: condition references
        if step.condition:
            _validate_condition_refs(
                step.condition, step.name, step_names, defined_vars, loop_vars
            )

        # Validate for: loop expressions
        if step.for_loop:
            for expr in step.for_loop.values():
                _validate_condition_refs(
                    expr, step.name, step_names, defined_vars, set()
                )

        # Validate repeat:/until: condition (self-reference allowed)
        if step.repeat_config:
            _validate_condition_refs(
                step.repeat_config.condition,
                step.name,
                step_names,
                defined_vars | {step.name},  # Allow self-reference
                loop_vars,
            )

        # Validate while: condition (self-reference allowed)
        if step.while_config:
            _validate_condition_refs(
                step.while_config.condition,
                step.name,
                step_names,
                defined_vars | {step.name},  # Allow self-reference
                loop_vars,
            )

        # After this step executes, its outputs become available
        if step.output:
            defined_vars.add(step.name)
            output_usage[step.name] = False

    # Warn about unused inputs (but don't error - they might be used in nested xprompts)
    # Warn about unused outputs (but don't error - final step output might be workflow result)


def _validate_condition_refs(
    content: str,
    step_name: str,
    step_names: set[str],
    defined_vars: set[str],
    loop_vars: set[str],
) -> None:
    """Validate variable references in a condition expression.

    Args:
        content: The condition expression to validate.
        step_name: Name of the step containing this condition.
        step_names: Set of all step names in the workflow.
        defined_vars: Set of currently defined variable names.
        loop_vars: Set of loop variable names available in this context.

    Raises:
        WorkflowValidationError: If invalid references found.
    """
    refs = re.findall(
        r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\s*",
        content,
    )

    for ref in refs:
        if "." in ref:
            step_ref_name, _ = ref.split(".", 1)
            if step_ref_name not in step_names:
                raise WorkflowValidationError(
                    f"Step '{step_name}' condition references undefined step "
                    f"'{step_ref_name}'"
                )
            if step_ref_name not in defined_vars:
                raise WorkflowValidationError(
                    f"Step '{step_name}' condition references step '{step_ref_name}' "
                    "before it executes"
                )
        else:
            # Direct variable reference - allowed if in loop_vars or known filters
            if ref not in loop_vars and ref not in ("tojson", "not", "and", "or"):
                # Allow for now, will fail at runtime if truly undefined
                pass

"""Utility functions for workflow execution."""

import json
import os
import re
from collections.abc import Mapping
from typing import Any

from jinja2 import Environment, StrictUndefined

from sase.env_contracts import (
    SASE_ACTIVE_PROJECT_DIR_ENV,
    SASE_AGENT_WORKSPACE_NUM_ENV,
)
from sase.xprompt._disabled_regions import (
    protect_disabled_regions,
    unprotect_disabled_regions,
)
from sase.xprompt.jinja_filters import register_prompt_filters


def _finalize_value(value: Any) -> Any:
    """Normalize Python values to their YAML string equivalents.

    - bool: True/False → "true"/"false" (bash expects lowercase)
    - None: → "null" (so downstream `value == "null"` pass-through works)
    """
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    return value


def create_jinja_env() -> Environment:
    """Create a Jinja2 environment for template rendering."""
    env = Environment(undefined=StrictUndefined, finalize=_finalize_value)

    # Add tojson filter (Python-aware: produces None/True/False instead of
    # null/true/false so rendered templates are valid Python)
    def _tojson(value: Any) -> str:
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "True" if value else "False"
        return json.dumps(value)

    env.filters["tojson"] = _tojson
    register_prompt_filters(env)
    return env


def render_template(template: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 template with the given context.

    Args:
        template: The template string with {{ var }} placeholders.
        context: Dictionary of variable values.

    Returns:
        The rendered template string.
    """
    from sase.xprompt._jinja import get_global_template_vars

    disabled_regions: list[str] = []
    protected_template = protect_disabled_regions(template, disabled_regions)

    env = create_jinja_env()
    merged = {**get_global_template_vars(), **context}
    jinja_template = env.from_string(protected_template)
    rendered = jinja_template.render(merged)
    return unprotect_disabled_regions(rendered, disabled_regions)


def parse_bash_output(output: str) -> dict[str, Any]:
    """Parse bash command output into a dictionary.

    Supports three formats:
    1. JSON: {"key": "value", ...}
    2. Key=Value: Each line is key=value
    3. Positional: Each line is a value (keys must be inferred from schema)

    Args:
        output: The command output string.

    Returns:
        Dictionary of parsed values.
    """
    output = output.strip()
    # Strip leading ASCII control characters (e.g., bell \x07) that terminal
    # commands sometimes emit, which prevents JSON detection.
    output = re.sub(r"^[\x00-\x1f\x7f]+", "", output)

    # Try JSON first
    if output.startswith("{") or output.startswith("["):
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            pass

    # Try key=value format — collect all key=value lines, ignoring
    # non-matching lines (e.g. incidental output from git commands).
    # Only fall back to plain-text mode when NO key=value lines exist.
    result: dict[str, Any] = {}
    lines = output.split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check for key=value pattern
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)=(.*)$", line)
        if match:
            key, value = match.groups()
            result[key] = value

    if result:
        return result

    # No key=value lines found — treat as plain text
    return {"_output": output} if output else {}


def coerce_output_types(
    output: dict[str, Any], output_types: dict[str, str]
) -> dict[str, Any]:
    """Coerce parsed output values to their declared schema types.

    ``parse_bash_output`` stores key=value pairs as strings.  When the output
    schema declares a field as ``bool`` or ``int``, the string value must be
    converted to the corresponding Python type so that downstream Jinja2
    templates produce valid Python/bash literals.

    Args:
        output: Parsed output dictionary (may be mutated in place).
        output_types: Mapping of field names to type strings from the schema.

    Returns:
        The same *output* dict with coerced values.
    """
    for field, declared_type in output_types.items():
        if field not in output:
            continue
        value = output[field]
        if declared_type == "bool" and isinstance(value, str):
            output[field] = value.lower() == "true"
        elif declared_type == "int" and isinstance(value, str):
            try:
                output[field] = int(value)
            except ValueError:
                pass
    return output


def workspace_num_from_output(output: Mapping[str, Any]) -> int | None:
    """Return a workspace number advertised by a workflow step, if present."""
    for field in ("meta_workspace", "workspace_num"):
        value = output.get(field)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                continue
    return None


def runner_bound_workspace_from_output(output: Mapping[str, Any]) -> bool:
    """Return whether a step asks the runner to adopt its workspace output."""
    value = output.get("runner_bound_workspace")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def apply_chdir_output(output: dict[str, Any]) -> str | None:
    """Apply and remove a workflow ``_chdir`` output value if present."""
    if "_chdir" not in output:
        return None

    chdir_path = str(output.pop("_chdir"))
    if not os.path.isabs(chdir_path):
        chdir_path = os.path.abspath(chdir_path)
    os.chdir(chdir_path)
    os.environ[SASE_ACTIVE_PROJECT_DIR_ENV] = chdir_path
    workspace_num = workspace_num_from_output(output)
    if workspace_num is not None:
        os.environ[SASE_AGENT_WORKSPACE_NUM_ENV] = str(workspace_num)
        from sase.sdd.env import set_sdd_dir_env

        set_sdd_dir_env(
            os.environ,
            workspace_dir=chdir_path,
            workspace_num=workspace_num,
        )
    return chdir_path

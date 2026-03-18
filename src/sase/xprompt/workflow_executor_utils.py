"""Utility functions for workflow execution."""

import json
import re
from typing import Any

from jinja2 import Environment, StrictUndefined


def _finalize_value(value: Any) -> Any:
    """Convert Python booleans to lowercase strings for bash compatibility.

    Jinja2 renders Python True/False as "True"/"False", but bash expects
    "true"/"false" for comparisons like [ "$var" = "true" ].
    """
    if isinstance(value, bool):
        return str(value).lower()
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

    env = create_jinja_env()
    merged = {**get_global_template_vars(), **context}
    jinja_template = env.from_string(template)
    return jinja_template.render(merged)


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

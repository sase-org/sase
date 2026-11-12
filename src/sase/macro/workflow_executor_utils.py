"""Utility functions for workflow execution."""

import json
import os
import re
import shlex
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from jinja2 import Environment, StrictUndefined

from sase.env_contracts import (
    SASE_ACTIVE_PROJECT_DIR_ENV,
    SASE_AGENT_WORKSPACE_NUM_ENV,
)
from sase.macro._disabled_regions import (
    protect_disabled_regions,
    unprotect_disabled_regions,
    wrap_disabled_region,
)
from sase.macro.jinja_filters import register_prompt_filters


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


class _RawShellText(str):
    """A string that bypasses shell quoting in ``bash:`` step rendering.

    Produced only by the ``| raw`` Jinja filter. Every other interpolation
    in a ``bash:`` template is passed through :func:`shlex.quote`, so an
    author who needs intentional raw splicing (e.g. pre-quoted flag groups)
    must opt out explicitly per interpolation.
    """


class _PythonLiteral(str):
    """A string that is already a valid Python literal for ``python:`` steps.

    Produced by the ``tojson`` filter in the python-step Jinja environment,
    so ``{{ value | tojson }}`` keeps splicing a Python literal (dict, list,
    string, number, bool, None) instead of being wrapped in ``repr``.
    """


def _finalize_bash_value(value: Any) -> str:
    """Finalize one ``{{ ... }}`` interpolation inside a ``bash:`` step.

    Values are normalized with :func:`_finalize_value` (bools → lowercase
    ``"true"``/``"false"``, None → ``"null"``) and then shell-quoted with
    :func:`shlex.quote`, so hostile content from macro inputs, prior step
    outputs, or model responses cannot break out of its shell word.
    ``| raw`` (a :class:`_RawShellText`) is the only opt-out.
    """
    if isinstance(value, _RawShellText):
        return str(value)
    normalized = _finalize_value(value)
    if not isinstance(normalized, str):
        normalized = str(normalized)
    return shlex.quote(normalized)


def _finalize_python_value(value: Any) -> str:
    """Finalize one ``{{ ... }}`` interpolation inside a ``python:`` step.

    Plain values are rendered with :func:`repr`, which yields a valid Python
    literal for strings (quoted), numbers, bools, None, and builtin
    containers — so hostile text cannot break out of the spliced source.
    ``| tojson`` output (already a Python literal) and ``| raw`` pass
    through unchanged.
    """
    if isinstance(value, (_RawShellText, _PythonLiteral)):
        return str(value)
    return repr(value)


def _raw_filter(value: Any) -> _RawShellText:
    """Opt out of quoting for one interpolation: ``{{ value | raw }}``.

    The value is spliced verbatim (no ``shlex.quote``/``repr`` and no
    bool/None normalization). Authors must only use this for values they
    constructed themselves (e.g. pre-quoted flag groups), never for macro
    inputs, step outputs, or model responses.
    """
    if isinstance(value, _RawShellText):
        return value
    return _RawShellText(str(value))


def _build_script_env(
    finalize: Any,
    *,
    python_literals: bool,
) -> Environment:
    """Create a Jinja2 environment for ``bash:``/``python:`` step bodies."""
    env = Environment(undefined=StrictUndefined, finalize=finalize)

    # tojson (Python-aware: produces None/True/False instead of
    # null/true/false so rendered templates are valid Python)
    def _tojson(value: Any) -> str:
        if value is None:
            result = "None"
        elif isinstance(value, bool):
            result = "True" if value else "False"
        else:
            result = json.dumps(value)
        if python_literals:
            return _PythonLiteral(result)
        return result

    env.filters["tojson"] = _tojson
    env.filters["raw"] = _raw_filter
    register_prompt_filters(env)
    return env


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


def _create_bash_jinja_env() -> Environment:
    """Create a Jinja2 environment for ``bash:`` step bodies.

    Every ``{{ ... }}`` interpolation is shell-quoted with
    :func:`shlex.quote` (after bool/None normalization), so untrusted values
    stay inside a single shell word. ``{{ value | raw }}`` opts out per
    interpolation for author-constructed fragments.
    """
    return _build_script_env(_finalize_bash_value, python_literals=False)


def _create_python_jinja_env() -> Environment:
    """Create a Jinja2 environment for ``python:`` step bodies.

    Every ``{{ ... }}`` interpolation is rendered with :func:`repr`, which
    yields a valid Python literal, so untrusted text cannot break out of the
    spliced source. ``{{ value | tojson }}`` (already a Python literal) and
    ``{{ value | raw }}`` pass through unchanged.
    """
    return _build_script_env(_finalize_python_value, python_literals=True)


def _render_with_env(template: str, context: dict[str, Any], env: Environment) -> str:
    from sase.macro._jinja import get_global_template_vars

    disabled_regions: list[str] = []
    protected_template = protect_disabled_regions(template, disabled_regions)

    merged = {**get_global_template_vars(), **context}
    jinja_template = env.from_string(protected_template)
    rendered = jinja_template.render(merged)
    return unprotect_disabled_regions(rendered, disabled_regions)


def render_template(template: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 template with the given context.

    Args:
        template: The template string with {{ var }} placeholders.
        context: Dictionary of variable values.

    Returns:
        The rendered template string.
    """
    return _render_with_env(template, context, create_jinja_env())


def render_bash_template(template: str, context: dict[str, Any]) -> str:
    """Render a ``bash:`` step body with shell-quoted interpolations.

    Args:
        template: The step body with {{ var }} placeholders.
        context: Dictionary of variable values.

    Returns:
        The rendered shell command with every interpolation quoted.
    """
    return _render_with_env(template, context, _create_bash_jinja_env())


def render_python_template(template: str, context: dict[str, Any]) -> str:
    """Render a ``python:`` step body with Python-literal interpolations.

    Args:
        template: The step body with {{ var }} placeholders.
        context: Dictionary of variable values.

    Returns:
        The rendered Python source with every interpolation repr-quoted.
    """
    return _render_with_env(template, context, _create_python_jinja_env())


def _wrap_model_output_values(
    value: Any,
    replacements: dict[str, str],
    *,
    nonce: str,
) -> Any:
    """Wrap workflow model output fields before they enter a prompt template."""
    if isinstance(value, Mapping):
        wrapped: dict[str, Any] = {}
        changed = False
        for key, item in value.items():
            if key in {"_raw", "_response"} and isinstance(item, str):
                placeholder = f"__SASE_MODEL_OUTPUT_{nonce}_{len(replacements)}__"
                replacements[placeholder] = wrap_disabled_region(item)
                wrapped[str(key)] = placeholder
                changed = True
            else:
                wrapped_item = _wrap_model_output_values(
                    item, replacements, nonce=nonce
                )
                wrapped[str(key)] = wrapped_item
                changed = changed or wrapped_item is not item
        return wrapped if changed else value
    if isinstance(value, list):
        wrapped_list = [
            _wrap_model_output_values(item, replacements, nonce=nonce) for item in value
        ]
        return (
            wrapped_list
            if any(
                wrapped_item is not item
                for wrapped_item, item in zip(wrapped_list, value, strict=True)
            )
            else value
        )
    if isinstance(value, tuple):
        wrapped_tuple = tuple(
            _wrap_model_output_values(item, replacements, nonce=nonce) for item in value
        )
        return (
            wrapped_tuple
            if any(
                wrapped_item is not item
                for wrapped_item, item in zip(wrapped_tuple, value, strict=True)
            )
            else value
        )
    return value


def render_prompt_template(template: str, context: dict[str, Any]) -> str:
    """Render prompt Jinja with model output held inside disabled regions."""
    replacements: dict[str, str] = {}
    rendered = render_template(
        template,
        _wrap_model_output_values(context, replacements, nonce=uuid4().hex),
    )
    for placeholder, protected_value in replacements.items():
        start = rendered.find(placeholder)
        if start < 0:
            continue
        end = start + len(placeholder)
        prefix = rendered[:start]
        suffix = rendered[end:]
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if suffix and not suffix.startswith("\n"):
            suffix = "\n" + suffix
        rendered = prefix + protected_value + suffix
    return rendered


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

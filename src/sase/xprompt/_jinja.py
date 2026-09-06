"""Jinja2 template handling and placeholder substitution."""

import re
import sys
from typing import Any

from jinja2 import BaseLoader, Environment, StrictUndefined, TemplateError
from sase.output import print_status

from ._exceptions import XPromptArgumentError
from ._fenced_blocks import (
    protect_fenced_blocks,
    protect_fenced_blocks_only,
    unprotect_fenced_blocks,
)
from .jinja_filters import register_prompt_filters
from .models import XPrompt

# Lazy-initialized Jinja2 environment
_jinja_env: Environment | None = None

# Top-level names reserved by the renderer, even when a runtime value cannot be
# resolved in the current process context.
RESERVED_GLOBAL_NAMES: frozenset[str] = frozenset({"root"})

# Static mirror of user-typeable top-level names injected by
# ``sase.axe.run_agent_exec._build_named_args`` or the runtime render context
# during agent runs. ``agents`` mirrors
# ``sase.agent.output_variable_context.AGENTS_CONTEXT_KEY``; keep the literal
# local to avoid importing the agent package from low-level xprompt helpers.
# Internal double-underscore workflow args are intentionally omitted.
BUILTIN_RUNTIME_NAMES: frozenset[str] = frozenset(
    {
        "cl_name",
        "workspace_num",
        "n",
        "N",
        "wait",
        "wait_chats",
        "agents",
    }
)


def is_jinja2_template(content: str) -> bool:
    """Detect if content uses Jinja2 syntax.

    Returns True if the content contains Jinja2 markers:
    - {{ ... }} for variable interpolation
    - {% ... %} for control structures
    - {# ... #} for comments
    """
    return bool(
        re.search(r"\{\{.*?\}\}", content, re.DOTALL)
        or re.search(r"\{%.*?%\}", content, re.DOTALL)
        or re.search(r"\{#.*?#\}", content, re.DOTALL)
    )


def _get_jinja_env() -> Environment:
    """Get or create the Jinja2 environment."""
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=BaseLoader(),
            undefined=StrictUndefined,
            autoescape=False,
        )
        register_prompt_filters(_jinja_env)
    return _jinja_env


def get_jinja_env() -> Environment:
    """Return the Jinja2 environment used by prompt rendering."""
    return _get_jinja_env()


def get_global_template_vars() -> dict[str, Any]:
    """Compute global Jinja2 template variables available to all prompts.

    Currently provides:
        root: Absolute path to the primary (#1) workspace directory for the
              current project, or omitted if the project can't be resolved.

    Static linting and completion use :data:`RESERVED_GLOBAL_NAMES` and
    :data:`BUILTIN_RUNTIME_NAMES` directly instead of inspecting runtime values.
    """
    from sase.bead.workspace import resolve_primary_workspace
    from sase.xprompt.runtime_context import get_runtime_template_vars

    result: dict[str, Any] = {}
    primary = resolve_primary_workspace()
    if primary is not None:
        result["root"] = str(primary)
    result.update(get_runtime_template_vars())
    return result


def validate_and_convert_args(
    xprompt: XPrompt,
    positional_args: list[str],
    named_args: dict[str, str],
) -> tuple[list[Any], dict[str, Any]]:
    """Validate and convert arguments using xprompt's input definitions.

    Args:
        xprompt: The XPrompt with input definitions.
        positional_args: Raw positional argument strings.
        named_args: Raw named argument strings.

    Returns:
        Tuple of (converted_positional, converted_named).

    Raises:
        XPromptArgumentError: If validation fails.
    """
    from .input_binding import InputBindingError, bind_input_args

    try:
        bound = bind_input_args(xprompt.inputs, positional_args, named_args)
    except InputBindingError as exc:
        raise XPromptArgumentError(
            f"XPrompt '#{xprompt.name}' argument error: {exc}"
        ) from exc
    return bound.positional, bound.values


def _render_jinja2_template(
    content: str,
    positional_args: list[Any],
    named_args: dict[str, Any],
    xprompt_name: str,
    scope: dict[str, Any] | None = None,
) -> str:
    """Render xprompt content as a Jinja2 template.

    Args:
        content: The Jinja2 template content
        positional_args: List of positional argument values
        named_args: Dictionary of named argument values
        xprompt_name: Name of the xprompt (for error messages)
        scope: Optional base context (e.g., workflow execution context).
            Xprompt-specific args take priority over scope values.

    Returns:
        Rendered template content

    Raises:
        XPromptArgumentError: On template errors or missing variables
    """
    env = _get_jinja_env()

    # Build context: globals first, then scope, then positional/named args override
    context: dict[str, Any] = get_global_template_vars()
    if scope:
        context.update(scope)
    for i, arg in enumerate(positional_args, 1):
        context[f"_{i}"] = arg
    context["_args"] = positional_args

    # Add named args directly (overrides scope)
    context.update(named_args)

    try:
        template = env.from_string(content)
        return template.render(**context)
    except TemplateError as e:
        raise XPromptArgumentError(
            f"XPrompt '#{xprompt_name}' template error: {e}"
        ) from e


def render_toplevel_jinja2(content: str) -> str:
    """Render top-level prompt content as a Jinja2 template.

    Unlike xprompt rendering, this has no arguments - it just processes
    Jinja2 syntax in the prompt itself.

    Args:
        content: The prompt content that may contain Jinja2 syntax

    Returns:
        Rendered content

    Raises:
        SystemExit: On template errors
    """
    fenced_blocks: list[str] = []
    content = protect_fenced_blocks(content, fenced_blocks)

    env = _get_jinja_env()
    try:
        template = env.from_string(content)
        content = template.render(**get_global_template_vars())
    except TemplateError as e:
        print_status(f"Jinja2 template error in prompt: {e}", "error")
        sys.exit(1)

    return unprotect_fenced_blocks(content, fenced_blocks)


def _substitute_legacy_placeholders(
    content: str, args: list[Any], xprompt_name: str
) -> str:
    """Substitute {1}, {2}, etc. placeholders with arguments (legacy mode).

    Also handles optional placeholders with defaults: {1:default}

    Args:
        content: The xprompt content with placeholders
        args: List of argument values
        xprompt_name: Name of the xprompt (for error messages)

    Returns:
        Content with placeholders replaced

    Raises:
        XPromptArgumentError: If required placeholder is missing an argument
    """
    # Find all placeholders: {1}, {2}, {1:default}, etc.
    placeholder_pattern = r"\{(\d+)(?::([^}]*))?\}"

    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1  # Convert to 0-based
        default = match.group(2)

        if index < len(args):
            return str(args[index])
        elif default is not None:
            return default
        else:
            raise XPromptArgumentError(
                f"XPrompt '#{xprompt_name}' requires argument {{{index + 1}}} "
                f"but only {len(args)} argument(s) provided"
            )

    return re.sub(placeholder_pattern, replace, content)


def substitute_placeholders(
    content: str,
    positional_args: list[Any],
    named_args: dict[str, Any],
    xprompt_name: str,
    scope: dict[str, Any] | None = None,
) -> str:
    """Substitute placeholders using appropriate mode (Jinja2 or legacy).

    Automatically detects whether to use Jinja2 or legacy substitution
    based on the content.
    """
    fenced_blocks: list[str] = []
    content = protect_fenced_blocks_only(content, fenced_blocks)

    if is_jinja2_template(content):
        result = _render_jinja2_template(
            content, positional_args, named_args, xprompt_name, scope=scope
        )
    else:
        result = _substitute_legacy_placeholders(content, positional_args, xprompt_name)

    return unprotect_fenced_blocks(result, fenced_blocks)

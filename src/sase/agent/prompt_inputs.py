"""Launch-time collection & substitution of prompt frontmatter ``input:`` values.

Phase 5 of the prompt-frontmatter-panel epic. When a submitted prompt's YAML
frontmatter declares ``input:`` arguments, those values must be rendered into
each prompt segment *before* the agents fan out. Required (default-less) inputs
are collected interactively in the TUI via the Input Collection Modal; optional
inputs fall back to their declared defaults. Non-interactive launches cannot
prompt, so they surface a clear error for missing required inputs rather than
failing later with a cryptic ``StrictUndefined`` Jinja error.

This module is pure logic (no Textual): it reuses the existing runtime parsers
(:func:`parse_yaml_front_matter`, :func:`parse_inputs_from_front_matter`), value
coercion (:meth:`InputArg.validate_and_convert`), and Jinja substitution
(:func:`substitute_placeholders`) so nothing here reimplements parsing,
validation, or rendering. ``input`` is canonical and ``inputs`` is accepted as an
alias, matching :class:`sase.xprompt.prompt_frontmatter.PromptFrontmatter`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase.xprompt._exceptions import XPromptArgumentError
from sase.xprompt._jinja import is_jinja2_template, substitute_placeholders
from sase.xprompt.loader_parsing import (
    parse_inputs_from_front_matter,
    parse_yaml_front_matter,
)
from sase.xprompt.models import UNSET, InputArg, XPromptValidationError

# Frontmatter keys that declare prompt inputs (``input`` canonical, ``inputs``
# accepted as an alias). Both are consumed/removed by ``render_prompt_with_inputs``.
_INPUT_KEYS = ("input", "inputs")

# ``xprompt_name`` handed to ``substitute_placeholders`` for error messages.
_SUBSTITUTION_SOURCE = "prompt-input"


class PromptInputError(Exception):
    """Raised when declared input values cannot be resolved or substituted."""


@dataclass(frozen=True)
class PromptInputRequest:
    """The ``input:`` arguments declared by a submitted prompt's frontmatter."""

    inputs: list[InputArg]

    @property
    def required(self) -> list[InputArg]:
        """Declared inputs with no default (the user must supply a value)."""
        return [arg for arg in self.inputs if arg.default is UNSET]

    @property
    def optional(self) -> list[InputArg]:
        """Declared inputs carrying a default (collection may be skipped)."""
        return [arg for arg in self.inputs if arg.default is not UNSET]

    @property
    def has_required(self) -> bool:
        """True when at least one declared input lacks a default."""
        return any(arg.default is UNSET for arg in self.inputs)


def parse_prompt_input_request(prompt: str) -> PromptInputRequest | None:
    """Return the inputs declared by *prompt*'s frontmatter, or ``None``.

    Returns ``None`` when the prompt has no frontmatter or declares no ``input``/
    ``inputs`` key, so callers can cheaply gate on "does this prompt need input
    collection at all?".
    """
    front_matter, _ = parse_yaml_front_matter(prompt)
    if front_matter is None:
        return None
    input_data = _extract_input_data(front_matter)
    if not input_data:
        return None
    inputs = parse_inputs_from_front_matter(input_data)
    if not inputs:
        return None
    return PromptInputRequest(inputs=inputs)


def missing_required_input_names(prompt: str) -> list[str]:
    """Return the names of required (default-less) inputs declared by *prompt*.

    Used by non-interactive launch paths to emit a clear error before the agent
    subprocess fails on an undefined Jinja variable.
    """
    request = parse_prompt_input_request(prompt)
    if request is None:
        return []
    return [arg.name for arg in request.required]


def _resolve_input_values(
    inputs: list[InputArg],
    raw_values: dict[str, str],
) -> dict[str, object]:
    """Convert raw string values to typed values, filling declared defaults.

    Args:
        inputs: Declared input arguments.
        raw_values: Raw user-entered string values keyed by input name. Only the
            inputs the user actually supplied need appear; others fall back to
            their declared default.

    Returns:
        Mapping of input name to typed value for every declared input that has a
        value (supplied or defaulted).

    Raises:
        PromptInputError: If a required input has no supplied value, or a
            supplied value fails :meth:`InputArg.validate_and_convert`.
    """
    resolved: dict[str, object] = {}
    for arg in inputs:
        if arg.name in raw_values:
            try:
                resolved[arg.name] = arg.validate_and_convert(raw_values[arg.name])
            except XPromptValidationError as exc:
                raise PromptInputError(str(exc)) from exc
        elif arg.default is UNSET:
            raise PromptInputError(f"Missing required input '{arg.name}'")
        else:
            resolved[arg.name] = arg.default
    return resolved


def render_prompt_with_inputs(prompt: str, raw_values: dict[str, str]) -> str:
    """Substitute declared input values into *prompt* and drop the ``input:`` block.

    Resolves typed values (supplied values plus declared defaults), renders every
    Jinja placeholder in the body via :func:`substitute_placeholders`, and
    re-emits the prompt with the consumed ``input``/``inputs`` frontmatter keys
    removed. Any other frontmatter (e.g. ``xprompts``) is preserved so local
    xprompts still flow to launch. A prompt that declares no inputs is returned
    unchanged.

    Args:
        prompt: The raw submitted prompt (frontmatter + body).
        raw_values: Raw string values for the declared inputs, keyed by name.

    Raises:
        PromptInputError: If a required input is missing/invalid, or the body's
            Jinja substitution fails (e.g. an undeclared placeholder).
    """
    front_matter, body = parse_yaml_front_matter(prompt)
    if front_matter is None:
        return prompt
    input_data = _extract_input_data(front_matter)
    if not input_data:
        return prompt

    inputs = parse_inputs_from_front_matter(input_data)
    values = _resolve_input_values(inputs, raw_values)

    rendered_body = body
    # Named inputs only make sense for Jinja bodies; skip legacy `{1}`
    # positional substitution so a plain body with declared-but-unused inputs is
    # returned untouched.
    if is_jinja2_template(body):
        try:
            rendered_body = substitute_placeholders(
                body, [], values, _SUBSTITUTION_SOURCE
            )
        except XPromptArgumentError as exc:
            raise PromptInputError(str(exc)) from exc

    remaining = {
        key: value for key, value in front_matter.items() if key not in _INPUT_KEYS
    }
    return _reattach_front_matter(remaining, rendered_body)


def _extract_input_data(front_matter: dict[str, Any]) -> Any:
    """Return the ``input`` value (or the ``inputs`` alias) from *front_matter*."""
    if "input" in front_matter:
        return front_matter["input"]
    return front_matter.get("inputs")


def _reattach_front_matter(front_matter: dict[str, object], body: str) -> str:
    """Re-emit a ``---``-delimited frontmatter block above *body*.

    Returns *body* unchanged when no frontmatter remains, so a prompt whose only
    frontmatter was the consumed ``input`` block launches as a bare prompt.
    """
    if not front_matter:
        return body
    dumped = yaml.safe_dump(
        front_matter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    return f"---\n{dumped}---\n{body}"


__all__ = [
    "PromptInputError",
    "PromptInputRequest",
    "missing_required_input_names",
    "parse_prompt_input_request",
    "render_prompt_with_inputs",
]

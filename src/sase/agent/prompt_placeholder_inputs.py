"""Unified launch-time collection plan for raw placeholders and declared inputs.

This module stays pure logic: it scans only the prompt body for raw
``<placeholder>`` fields, reuses the existing frontmatter ``input:`` parser, and
applies collected values in the same order the TUI launch path will use.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sase.agent.prompt_inputs import (
    PromptInputRequest,
    parse_prompt_input_request,
    render_prompt_with_inputs,
)
from sase.config.core import load_merged_config
from sase.xprompt.loader_parsing import parse_yaml_front_matter
from sase.xprompt.raw_placeholders import (
    RawPlaceholderField,
    raw_placeholder_fields,
    substitute_raw_placeholders,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromptInputPlan:
    """Everything a submitted prompt needs collected, in display order."""

    placeholders: tuple[RawPlaceholderField, ...]
    declared: PromptInputRequest | None

    @property
    def needs_collection(self) -> bool:
        """True when launch must ask the user for at least one value."""
        return bool(self.placeholders) or (
            self.declared is not None and self.declared.has_required
        )


@dataclass(frozen=True)
class PromptInputValues:
    """Collected prompt values keyed by their exact prompt field names."""

    placeholders: dict[str, str]
    declared: dict[str, str]


def build_prompt_input_plan(prompt: str) -> PromptInputPlan:
    """Return the raw-placeholder and declared-input collection plan for *prompt*.

    YAML frontmatter is treated as configuration and is not scanned for raw
    placeholders. When ``ace.prompt_inputs.collect_raw_placeholders`` is
    disabled the plan carries no placeholder fields, so the launch path behaves
    exactly as it did before submit-time collection existed.
    """
    placeholders: tuple[RawPlaceholderField, ...] = ()
    if _collect_raw_placeholders_enabled():
        placeholders = raw_placeholder_fields(parse_yaml_front_matter(prompt)[1])
    return PromptInputPlan(
        placeholders=placeholders,
        declared=parse_prompt_input_request(prompt),
    )


def _collect_raw_placeholders_enabled() -> bool:
    """Return whether submit-time raw-placeholder collection is enabled.

    Reads ``ace.prompt_inputs.collect_raw_placeholders`` through the cached
    merged config so the prompt-submit path does no extra disk I/O. A missing,
    unreadable, or unparsable value falls back to enabled.
    """
    try:
        ace = _config_section(load_merged_config(), "ace")
        raw = _config_section(ace, "prompt_inputs").get(
            "collect_raw_placeholders", True
        )
    except Exception:
        log.debug("raw placeholder collection toggle unavailable", exc_info=True)
        return True
    return bool(raw)


def _config_section(data: object, key: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    section = data.get(key)
    return section if isinstance(section, dict) else {}


def apply_prompt_input_values(prompt: str, values: PromptInputValues) -> str:
    """Apply collected placeholder and declared input values to *prompt*.

    Raw placeholders are substituted into the body first, then declared inputs
    are rendered through :func:`render_prompt_with_inputs`. ``PromptInputError``
    is intentionally not wrapped so callers keep the existing input-error path.
    """
    frontmatter, body = _split_raw_frontmatter(prompt)
    substituted_body = substitute_raw_placeholders(body, values.placeholders)
    substituted_prompt = _attach_raw_frontmatter(frontmatter, substituted_body)
    return render_prompt_with_inputs(substituted_prompt, values.declared)


def _split_raw_frontmatter(prompt: str) -> tuple[str, str]:
    """Return ``(raw_frontmatter, body)`` using the canonical parser's validity.

    ``raw_frontmatter`` includes both ``---`` delimiters and excludes the
    following newline. When the prompt has no valid YAML frontmatter, the full
    prompt is returned as the body.
    """
    parsed_frontmatter, body = parse_yaml_front_matter(prompt)
    if parsed_frontmatter is None:
        return "", prompt

    lines = prompt.split("\n")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[: index + 1]), body
    return "", prompt


def _attach_raw_frontmatter(frontmatter: str, body: str) -> str:
    if not frontmatter:
        return body
    return f"{frontmatter}\n{body}" if body else frontmatter


__all__ = [
    "PromptInputPlan",
    "PromptInputValues",
    "build_prompt_input_plan",
    "apply_prompt_input_values",
]

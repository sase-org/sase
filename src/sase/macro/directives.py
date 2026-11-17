"""Prompt directive parsing (%id tag system).

Directives are in-prompt tags with a ``%`` prefix that modify runner behavior.
They are extracted and stripped from the prompt before further preprocessing.
Directive arguments use the same syntax as macros (colon, paren, backtick, plus).

Example::

    %model:agy/gemini-3.6-flash-low
    Review this code...

The ``%model`` directive overrides the LLM model used for that prompt. Its
parenthesized form also accepts agent-session-scoped alias overrides, for example
``%model(opus, coder=sonnet)``.

The implementation is split across a few private sibling modules:

- :mod:`._directive_extract` — :func:`extract_prompt_directives` implementation.
- :mod:`._directive_scan` — cheap ``has_*`` predicates and
  :func:`strip_known_directives`.
- :mod:`._directive_types` — :class:`PromptDirectives` dataclass and the
  shared regex/alias tables.
- :mod:`._directive_time` — duration / absolute-time argument parsing for
  ``%wait``.
- :mod:`._directive_alt` — ``%alt(...)`` / ``%(...)`` splitting and the
  multi-model fan-out used by :func:`split_prompt_for_models`.

This module is the public entry point and compatibility facade.
"""

import sys

from sase._lazy_exports import lazy_getattr

from ._directive_alt import (
    apply_fanout_naming,
    has_alt_directive,
    plan_prompt_fanout_variants,
    split_prompt_for_alternatives,
    split_prompt_for_models,
)
from collections.abc import Callable


from ._directive_extract import extract_prompt_directives as _extract_prompt_directives
from ._directive_scan import (
    has_deferred_start_directive,
    has_model_directive,
    has_runner_threshold_directive,
    has_typed_launch_directive,
    strip_known_directives,
)
from ._directive_time import parse_absolute_time, parse_duration
from ._directive_types import PromptDirectives
from ._exceptions import DirectiveError
from .directive_diagnostics import (
    RetiredDirectiveUsage,
    find_retired_directive_usages,
)
from .hold_directive import (
    HoldFields,
    format_hold_directive,
    hold_fields_to_selectors,
)

__all__ = [
    "DirectiveError",
    "HoldFields",
    "PromptDirectives",
    "RetiredDirectiveUsage",
    "apply_fanout_naming",
    "extract_prompt_directives",
    "find_retired_directive_usages",
    "format_hold_directive",
    "has_alt_directive",
    "has_deferred_start_directive",
    "has_model_directive",
    "has_runner_threshold_directive",
    "has_typed_launch_directive",
    "hold_fields_to_selectors",
    "parse_absolute_time",
    "parse_duration",
    "plan_prompt_fanout_variants",
    "split_prompt_for_alternatives",
    "split_prompt_for_models",
    "strip_known_directives",
]

_LAZY_EXPORTS = {
    "process_macro_references": ("sase.macro.processor", "process_macro_references"),
}


def __getattr__(name: str) -> object:
    """Resolve process_macro_references without importing the macro processor."""
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


# PEP 562 entry points are called by Python, not by normal in-file code.
_PEP562_HOOKS = (__getattr__,)


def extract_prompt_directives(
    prompt: str,
    *,
    strip_disabled_markers: bool = True,
    reveal_values: Callable[[str], str] | None = None,
) -> tuple[str, PromptDirectives]:
    """Extract ``%id`` directives from a prompt.

    Finds all ``%id`` patterns in the prompt. Known directives are parsed,
    their macro references expanded, and they are stripped from the prompt.
    Unknown ``%id`` patterns are left in the prompt unchanged.

    Args:
        prompt: The raw prompt text.
        strip_disabled_markers: If True (default), strip
            ``%macros_enabled:false``/``%macros_enabled:true`` markers from
            the returned prompt. Set to False when this function is called as
            part of a multi-phase pipeline that needs to preserve the markers
            for a later phase (e.g. :func:`preprocess_prompt_early`).
        reveal_values: Optional hook restoring guard-hidden text inside
            collected directive values before validation. The prompt itself
            stays protected so interpolated data lines never parse as
            directives; pass a guard's unwrap when the prompt carries
            guard tokens from macro expansion or source rendering.

    Returns:
        Tuple of (cleaned_prompt, directives).

    Raises:
        DirectiveError: If a known single-value directive appears more than
            once. Top-level ``%model`` is single-value; repeated model
            directives and multi-argument ``%model(...)`` forms raise with a
            migration hint. Parenthesized ``%model`` accepts one positional
            model plus alias keyword overrides, or keyword overrides alone.
            Directives inside raw ``%alt(...)`` / ``%(...)`` /
            ``%{...}`` bodies are ignored until the fan-out planner splits
            those branches.
    """
    # Resolve through this module's namespace so the lazy export above
    # applies: the macro engine loads on first use, while explicit
    # attribute reuse (including test patch targets) is still honored.
    # Values are revealed from guard tokens for validation (see
    # reveal_values); the prompt itself stays protected.
    return _extract_prompt_directives(
        prompt,
        strip_disabled_markers=strip_disabled_markers,
        process_references=sys.modules[__name__].process_macro_references,
        reveal_values=reveal_values,
    )

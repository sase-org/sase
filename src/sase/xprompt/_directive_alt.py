"""``%alt(...)`` / ``%(...)`` / ``%{...}`` splitting and model fan-out.

This module owns the logic that turns a single prompt with explicit
``%alt(a,b,...)`` / ``%{a | b | ...}`` calls into a list of sub-prompts. A
``%model`` directive participates in fan-out only when it lives inside one of
those alternative branches. Unrelated directives form a Cartesian product,
while explicit branch names repeated across directives are correlated into the
same fan-out slot. Empty branch renders collapse adjacent horizontal whitespace
so variants do not keep doubled spaces or spaces before punctuation, while
newlines and indentation are preserved. The sibling ``_directive_alt_naming``
module owns the naming logic that disambiguates spawned agents per runtime.

``%{...}`` is the preferred shorthand for ``%alt(...)``; it uses braces
with top-level ``|``-separated branches.  The legacy ``%(...)`` shorthand
(comma-separated) remains parse-compatible during the migration.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from ._directive_alt_naming import (
    apply_fanout_naming,
    apply_fanout_naming_with_metadata,
)
from ._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
from ._disabled_regions import protect_disabled_regions
from ._exceptions import DirectiveError
from ._fenced_blocks import protect_fenced_blocks
from ._parsing import (
    find_matching_brace_for_args,
    find_matching_paren_for_args,
    parse_args,
)

if TYPE_CHECKING:
    from sase.core.agent_launch_wire import LaunchFanoutPlanWire

    from .models import XPrompt

# Pattern to match %alt(, %( or %{ at a directive-valid position, including
# directive value fan-out after a colon. The group captures through the opening
# delimiter so ``match.end() - 1`` is the ``(`` or ``{`` that opens the alt
# body. Mirrors ``alt_directive_re`` in the Rust core.
_ALT_DIRECTIVE_RE = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\[{\"':]))"
    r"(%(?:alt)?\(|%\{)",
    re.MULTILINE,
)


def _strip_model_alias_prefix(value: str) -> str:
    from sase.llm_provider.config import strip_model_alias_prefix

    return strip_model_alias_prefix(value)


def _runtime_label_for_model(model: str) -> str:
    """Map a model string to its runtime/provider label (e.g. ``"claude"``).

    Falls back to the configured default provider if the model is unknown
    — mirrors the resolution used in ``run_agent_phases.py``.
    """
    from sase.llm_provider.registry import (
        get_default_provider_name,
        provider_short_name_map,
        resolve_model_provider,
    )

    provider, _ = resolve_model_provider(_strip_model_alias_prefix(model))
    name = provider or get_default_provider_name()
    return provider_short_name_map().get(name, name)


def runtime_label_for_model(model: str) -> str:
    """Public wrapper for fan-out naming modules."""
    return _runtime_label_for_model(model)


def has_alt_directive(prompt: str) -> bool:
    """Quick check whether a prompt contains a ``%alt(``, ``%(`` or ``%{`` directive.

    This avoids the overhead of full splitting and is suitable for
    early detection in the ChangeSpecI auto-daemon routing.
    """
    if "%" not in prompt:
        return False

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)

    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    return _ALT_DIRECTIVE_RE.search(protected) is not None


def split_prompt_for_alternatives(prompt: str) -> list[str] | None:
    """Split a prompt with ``%alt(...)`` / ``%(...)`` / ``%{...}`` into per-alternative prompts.

    Each argument becomes a separate prompt with the directive span replaced
    by that argument's text.  Arguments can be arbitrary text — directives,
    xprompt references, plain instructions, or ``[[text blocks]]``.

    ``%{...}`` (top-level ``|``-separated branches) is the preferred shorthand
    for ``%alt(...)``; ``%(...)`` (comma-separated) is the legacy shorthand.

    When multiple ``%alt``/``%(``/``%{`` directives appear, unrelated branch
    lists form a Cartesian product — e.g. two directives with 2 and 3 arguments
    produce 2 × 3 = 6 prompts. If the same explicit branch name appears in more
    than one directive, those named branches are correlated into one slot; a
    missing key in a correlated directive renders as empty text.

    Empty renders collapse adjacent spaces/tabs when that avoids doubled
    spaces, leading/trailing spaces, or spaces before punctuation. Newlines and
    indentation are preserved, and non-empty branches are left unchanged.

    Returns ``None`` if there are no ``%alt``/``%(``/``%{`` directives or all
    have zero arguments.  A single-arg ``%alt(foo)`` / ``%(foo)`` / ``%{foo}``
    is treated as having an implicit empty variant, producing two alternatives
    for that directive.

    Raises:
        DirectiveError: If an opening delimiter has no matching close.
    """
    from sase.core.agent_launch_facade import plan_agent_launch_fanout

    try:
        plan = plan_agent_launch_fanout(prompt, launch_kind="alternatives")
    except ValueError as exc:
        raise DirectiveError(str(exc)) from exc
    if not plan.slots:
        return None
    return [slot.prompt for slot in plan.slots]


def split_prompt_for_models(
    prompt: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> list[str] | None:
    """Split a prompt with model-bearing ``%alt``/``%(``/``%{`` directives.

    ``%model`` / ``%m`` is a single-value directive. Multi-model fan-out must
    be expressed by putting one model directive in each alternative branch,
    e.g. ``%{%m:opus | %m:sonnet}``. Legacy multi-argument forms such as
    ``%m(opus,sonnet)`` and repeated top-level ``%model`` directives raise a
    :class:`DirectiveError` with a migration hint.

    Unrelated alt/model axes form a Cartesian product. Explicit branch names
    repeated across alt directives are correlated into one slot, while unnamed
    branches and disjoint names remain Cartesian. Empty alt renders collapse
    adjacent horizontal whitespace as in :func:`split_prompt_for_alternatives`.

    Returns ``None`` if there is no splitting directive at all, or if only a
    single top-level model directive is present and no alt directives produce
    slots.
    """
    plan = plan_prompt_fanout_variants(prompt, extra_xprompts=extra_xprompts)
    if plan is None:
        return None
    return [slot.prompt for slot in plan.slots]


def plan_prompt_fanout_variants(
    prompt: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> LaunchFanoutPlanWire | None:
    """Return a launch fan-out plan whose slots carry planned child names."""
    plan = _plan_prompt_fanout(prompt, extra_xprompts=extra_xprompts)
    if plan is None:
        return None

    named_prompts = apply_fanout_naming_with_metadata(
        plan,
        extra_xprompts=extra_xprompts,
    )
    slots = [
        replace(
            slot,
            prompt=named_prompt.prompt,
            name_generated=named_prompt.name_generated,
        )
        for slot, named_prompt in zip(plan.slots, named_prompts, strict=True)
    ]
    plan = replace(plan, slots=slots)
    if plan.launch_kind == "model" and all(slot.model is None for slot in plan.slots):
        plan = replace(
            plan,
            launch_kind="alternatives",
            slots=[replace(slot, launch_kind="alternatives") for slot in plan.slots],
        )
    return plan


def _plan_prompt_fanout(
    prompt: str,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
) -> LaunchFanoutPlanWire | None:
    if extra_xprompts is None and "#" not in prompt:
        # The Rust fan-out grammar intentionally remains single-positional for
        # ``%model(...)``. Keyword arguments are launch metadata, not a model
        # fan-out axis, so keep a scalar kwarg-bearing directive on the normal
        # extraction path instead of presenting its ``key=value`` tokens to the
        # Rust multi-model migration check.
        if not has_alt_directive(prompt) and _has_model_keyword_args(prompt):
            return None
        return _plan_model_fanout(prompt)

    if "%" not in prompt:
        return None

    # Protect fenced code blocks and disabled regions so %model directives
    # inside them are ignored.
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    # Identify inner regions of %alt(...) / %(...) / %{...} so %model matches
    # nested inside them are not double-collected (they're handled by
    # split_prompt_for_alternatives).
    alt_inner_regions: list[tuple[int, int]] = []
    for alt_match in _ALT_DIRECTIVE_RE.finditer(protected):
        open_pos = alt_match.end() - 1
        if protected[open_pos] == "{":
            close_pos = find_matching_brace_for_args(protected, open_pos)
        else:
            close_pos = find_matching_paren_for_args(protected, open_pos)
        if close_pos is None:
            continue
        alt_inner_regions.append((open_pos + 1, close_pos))

    def _is_inside_alt(pos: int) -> bool:
        return any(start <= pos < end for start, end in alt_inner_regions)

    # Walk all directive matches and pick out top-level %model / %m occurrences.
    valued_directive_spans: list[tuple[int, int, str]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        resolved = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
        if resolved != "model":
            continue
        if _is_inside_alt(match.start()):
            continue

        has_open_paren = match.group(2) is not None
        colon_arg = match.group(3)
        plus_suffix = match.group(4)

        match_end = match.end()
        args: list[str] = []

        if has_open_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                paren_content = protected[paren_start + 1 : paren_end]
                positional_args, _ = parse_args(paren_content)
                args = [a for a in positional_args if a]
                match_end = paren_end + 1
        elif colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                value = colon_arg[1:-1]
            else:
                value = colon_arg
            if value:
                args = [value]
        elif plus_suffix is not None:
            # %model+ is a plus-syntax sentinel with no real model value —
            # leave it alone for the extractor to handle.
            continue

        if len(args) > 1:
            source = protected[match.start() : match_end]
            raise DirectiveError(multi_model_unsupported_message(source, args))
        if args:
            valued_directive_spans.append((match.start(), match_end, args[0]))

    if len(valued_directive_spans) > 1:
        source = " ... ".join(
            protected[start:end] for start, end, _ in valued_directive_spans
        )
        models = [value for _, _, value in valued_directive_spans]
        raise DirectiveError(multi_model_unsupported_message(source, models))

    fanout_plan = _plan_model_fanout(prompt)
    if fanout_plan is None:
        return None
    return fanout_plan


def multi_model_unsupported_message(source: str, models: list[str]) -> str:
    replacement = " | ".join(f"%m:{model}" for model in models)
    return f"{source} is no longer supported; use %{{{replacement}}} instead"


def _plan_model_fanout(prompt: str) -> LaunchFanoutPlanWire | None:
    from sase.core.agent_launch_facade import plan_agent_launch_fanout

    try:
        plan = plan_agent_launch_fanout(prompt, launch_kind="model")
    except ValueError as exc:
        raise DirectiveError(str(exc)) from exc
    if not plan.slots:
        return None
    return plan


def _has_model_keyword_args(prompt: str) -> bool:
    """Return whether an active parenthesized ``%model`` has named args."""
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)
    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "model":
            continue
        if match.group(2) is None:
            continue
        paren_start = match.end() - 1
        paren_end = find_matching_paren_for_args(protected, paren_start)
        if paren_end is None:
            continue
        _, named_args = parse_args(protected[paren_start + 1 : paren_end])
        if named_args:
            return True
    return False
